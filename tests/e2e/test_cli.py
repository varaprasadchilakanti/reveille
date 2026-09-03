"""End-to-end tests for the Reveille CLI.

These tests invoke the CLI through Typer's CliRunner, which executes
the full application pipeline in-process: argument parsing, configuration
validation, Git data extraction, ranking, and HTML rendering. They
verify the externally observable contract: exit codes, stdout messages,
and the structure of the generated HTML output file.

Parallelism: tests run under pytest-xdist (-n auto). All fixtures use
tmp_path_factory rather than tmp_path to remain safe across workers.
The module-scoped default_report_content fixture generates the Plotly
bundle once per worker, avoiding redundant full-pipeline invocations
for tests that only inspect default output structure.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from reveille import __version__
from reveille.cli import ExitCode, app

runner = CliRunner()


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2e_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a minimal Git repository for end-to-end CLI testing.

    Contains three commits from two contributors across a two-month window,
    which is sufficient to exercise the full report generation pipeline.
    Module-scoped so the repository is created once per worker.
    """
    repo_path = tmp_path_factory.mktemp("e2e_repo")

    def run(args: list[str], env_override: dict[str, str] | None = None) -> None:
        env = {**os.environ, **(env_override or {})}
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

    alice = {
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_COMMITTER_DATE": "2024-02-01T10:00:00+00:00",
    }
    bob = {
        "GIT_AUTHOR_NAME": "Bob",
        "GIT_AUTHOR_EMAIL": "bob@example.com",
        "GIT_COMMITTER_NAME": "Bob",
        "GIT_COMMITTER_EMAIL": "bob@example.com",
        "GIT_COMMITTER_DATE": "2024-03-15T14:00:00+00:00",
    }

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "alice@example.com"])
    run(["git", "config", "user.name", "Alice"])

    (repo_path / "module_a.py").write_text("x = 1\ny = 2\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "feat: initial commit",
            "--date=2024-02-01T10:00:00+00:00",
        ],
        env_override=alice,
    )

    (repo_path / "module_b.py").write_text("a = 10\nb = 20\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "feat: add module_b",
            "--date=2024-03-15T14:00:00+00:00",
        ],
        env_override=bob,
    )

    (repo_path / "module_a.py").write_text("x = 1\ny = 2\nz = 3\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "fix: add z variable",
            "--date=2024-03-20T09:00:00+00:00",
        ],
        env_override={**alice, "GIT_COMMITTER_DATE": "2024-03-20T09:00:00+00:00"},
    )

    return repo_path


@pytest.fixture(scope="module")
def default_report_content(
    e2e_repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Generate the default report once and return its HTML content.

    Shared across all tests that inspect default output structure to avoid
    embedding the Plotly bundle multiple times per worker. Tests that
    exercise distinct flags generate their own outputs independently.
    """
    output = tmp_path_factory.mktemp("default_report") / "report.html"
    result = runner.invoke(
        app,
        ["generate", "--repo", str(e2e_repo), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    return output.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Version command
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestVersionCommand:
    """Tests for the reveille --version flag."""

    def test_version_outputs_correct_string(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_version_flag_short_form(self) -> None:
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_version_is_not_a_subcommand(self) -> None:
        """`reveille version` must fail, because the README once said it worked.

        The version string is exposed as a global flag. The README
        documented a `reveille version` subcommand through v0.6.x; it
        never existed, and anyone who copied it from the CLI reference
        got 'No such command'.
        """
        result = runner.invoke(app, ["version"])
        assert result.exit_code != 0


@pytest.mark.e2e
class TestDocumentedCommandsExist:
    """Every command in the README's CLI Reference must be real.

    A CLI reference is a promise. Documenting a command that does not
    exist is worse than omitting it, because a reader who copies it gets
    an error and no way to tell whether the tool or the documentation is
    wrong.
    """

    def _documented_commands(self) -> set[str]:
        readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
        # CLI Reference subsections read `### \`reveille <name>\``.
        # Flags are documented as `--flag`, so requiring a leading
        # lowercase letter excludes them from the command set.
        return set(re.findall(r"^### `reveille ([a-z][a-z-]*)`", readme, re.MULTILINE))

    def _registered_commands(self) -> set[str]:
        """Read the commands Typer actually registered.

        Deliberately not parsed out of `--help` text. An earlier version
        of this test did exactly that and passed while the README
        documented a command that did not exist -- the name matched
        inside an option's description sentence rather than the command
        list. Interrogating the group is exact.
        """
        return set(typer.main.get_command(app).commands)

    def test_registered_commands_are_discoverable(self) -> None:
        """Guard the guard: both checks are vacuous if either set is empty."""
        assert self._registered_commands()
        assert self._documented_commands()

    def test_readme_documents_commands_that_exist(self) -> None:
        missing = sorted(self._documented_commands() - self._registered_commands())
        assert not missing, f"README documents commands the CLI does not provide: {missing}"

    def test_every_real_command_is_documented(self) -> None:
        undocumented = sorted(self._registered_commands() - self._documented_commands())
        assert not undocumented, f"CLI provides commands the README omits: {undocumented}"


# ------------------------------------------------------------------
# Help command
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestHelpCommand:
    """Tests for the reveille help command."""

    def test_help_command_exits_zero(self) -> None:
        result = runner.invoke(app, ["help"])
        assert result.exit_code == 0

    def test_help_command_output_contains_known_subcommands(self) -> None:
        result = runner.invoke(app, ["help"])
        assert "generate" in result.output
        assert "init" in result.output
        assert "validate" in result.output


# ------------------------------------------------------------------
# Validate command
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestValidateCommand:
    """Tests for the reveille validate command."""

    def test_valid_repository_exits_zero(self, e2e_repo: Path) -> None:
        result = runner.invoke(app, ["validate", "--repo", str(e2e_repo)])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_non_git_directory_exits_nonzero(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        plain = tmp_path_factory.mktemp("plain_dir")
        result = runner.invoke(app, ["validate", "--repo", str(plain)])
        assert result.exit_code == ExitCode.CANNOT_RUN

    def test_non_git_directory_reports_error_in_output(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        plain = tmp_path_factory.mktemp("plain_dir_err")
        result = runner.invoke(app, ["validate", "--repo", str(plain)])
        assert "Error" in result.output

    def test_validate_exits_nonzero_when_repository_has_no_commits(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        empty_repo = tmp_path_factory.mktemp("validate_empty_repo")
        env = {**os.environ}
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=empty_repo,
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=empty_repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=empty_repo,
            check=True,
            capture_output=True,
        )
        result = runner.invoke(app, ["validate", "--repo", str(empty_repo)])
        assert result.exit_code == ExitCode.NEGATIVE


# ------------------------------------------------------------------
# Generate command
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestGenerateCommand:
    """Tests for the reveille generate command."""

    # -- Default output structure (shared fixture, no redundant rendering) --

    def test_generates_html_file_at_default_path(self, default_report_content: str) -> None:
        assert len(default_report_content) > 0

    def test_output_is_valid_html(self, default_report_content: str) -> None:
        assert "<!DOCTYPE html>" in default_report_content
        assert "</html>" in default_report_content

    def test_output_contains_plotly_bundle(self, default_report_content: str) -> None:
        assert "plotly" in default_report_content.lower()

    def test_output_contains_contributor_names(self, default_report_content: str) -> None:
        assert "Alice" in default_report_content
        assert "Bob" in default_report_content

    def test_output_file_has_no_external_script_tags(self, default_report_content: str) -> None:
        import re

        external_tags = re.findall(
            r'<script[^>]+src=["\']https?://',
            default_report_content,
        )
        assert external_tags == [], (
            f"Report contains {len(external_tags)} external script reference(s): {external_tags}"
        )

    # -- Distinct invocations (different flags, cannot share) --

    def test_stdout_reports_output_path(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        output = tmp_path_factory.mktemp("stdout_test") / "report.html"
        result = runner.invoke(
            app,
            ["generate", "--repo", str(e2e_repo), "--output", str(output)],
        )
        assert result.exit_code == 0
        assert "Report written to" in result.stdout

    def test_title_override_appears_in_output(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        output = tmp_path_factory.mktemp("title_test") / "report.html"
        runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--title",
                "Q1 Engineering Review",
            ],
        )
        content = output.read_text(encoding="utf-8")
        assert "Q1 Engineering Review" in content

    def test_no_ranking_flag_completes_successfully(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        output = tmp_path_factory.mktemp("no_ranking_test") / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--no-ranking",
            ],
        )
        assert result.exit_code == 0
        assert output.exists()

    def test_since_filter_restricts_analysis_window(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        output = tmp_path_factory.mktemp("since_test") / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--since",
                "2024-03-01",
            ],
        )
        assert result.exit_code == 0
        assert output.exists()

    # -- Error path tests (no rendering, fast) --

    def test_invalid_since_date_exits_nonzero(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        output = tmp_path_factory.mktemp("invalid_since") / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--since",
                "not-a-date",
            ],
        )
        assert result.exit_code == ExitCode.CANNOT_RUN

    def test_since_after_until_exits_nonzero(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        output = tmp_path_factory.mktemp("inverted_dates") / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--since",
                "2024-06-01",
                "--until",
                "2024-01-01",
            ],
        )
        assert result.exit_code == ExitCode.CANNOT_RUN

    def test_config_file_title_appears_in_output(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        base = tmp_path_factory.mktemp("config_title_test")
        output = base / "report.html"
        config_file = base / "reveille.toml"
        config_file.write_text(
            '[report]\ntitle = "TOML Config Title"\n',
            encoding="utf-8",
        )
        runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--config",
                str(config_file),
            ],
        )
        content = output.read_text(encoding="utf-8")
        assert "TOML Config Title" in content

    def test_cli_title_overrides_config_file_title(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        base = tmp_path_factory.mktemp("cli_override_test")
        output = base / "report.html"
        config_file = base / "reveille.toml"
        config_file.write_text(
            '[report]\ntitle = "Config Title"\n',
            encoding="utf-8",
        )
        runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--config",
                str(config_file),
                "--title",
                "CLI Title",
            ],
        )
        content = output.read_text(encoding="utf-8")
        assert "CLI Title" in content
        assert "Config Title" not in content

    def test_min_commits_cli_flag_overrides_config_file_value(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """--min-commits 1 takes precedence over min_commits = 2 in a config file.

        The e2e fixture contains Bob with one commit. A config file with
        min_commits = 2 would exclude him. Passing --min-commits 1 on the
        CLI must override the config value and include him in the output.
        """
        base = tmp_path_factory.mktemp("min_commits_override")
        output = base / "report.html"
        config_file = base / "reveille.toml"
        config_file.write_text(
            "[filters]\nmin_commits = 2\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--config",
                str(config_file),
                "--min-commits",
                "1",
            ],
        )
        assert result.exit_code == 0
        content = output.read_text(encoding="utf-8")
        assert "Bob" in content

    def test_nonexistent_config_file_exits_nonzero(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        base = tmp_path_factory.mktemp("missing_config_test")
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(base / "report.html"),
                "--config",
                str(base / "nonexistent.toml"),
            ],
        )
        assert result.exit_code == ExitCode.CANNOT_RUN

    def test_invalid_repo_path_exits_nonzero(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        base = tmp_path_factory.mktemp("invalid_repo_test")
        plain = base / "not_a_repo"
        plain.mkdir()
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(plain),
                "--output",
                str(base / "report.html"),
            ],
        )
        assert result.exit_code == ExitCode.CANNOT_RUN

    def test_output_embeds_heatmap_data_spec(self, default_report_content: str) -> None:
        """The compact heatmap data payload is embedded in the output."""
        assert 'id="spec-heatmap"' in default_report_content

    def test_output_contains_contributor_timeline_spec_block(
        self, default_report_content: str
    ) -> None:
        """The per-contributor timeline spec block is embedded in the output."""
        assert 'id="spec-contributor_timeline"' in default_report_content

    def test_auto_discovers_reveille_toml_in_cwd(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """reveille.toml at CWD is loaded without --config when present."""
        work_dir = tmp_path_factory.mktemp("auto_discover_cwd")
        output = work_dir / "report.html"
        (work_dir / "reveille.toml").write_text(
            '[report]\ntitle = "Auto Discovered Title"\n',
            encoding="utf-8",
        )
        original = Path(os.getcwd())
        try:
            os.chdir(work_dir)
            result = runner.invoke(
                app,
                ["generate", "--repo", str(e2e_repo), "--output", str(output)],
            )
        finally:
            os.chdir(original)
        assert result.exit_code == 0
        assert "Auto Discovered Title" in output.read_text(encoding="utf-8")

    def test_malformed_auto_discovered_config_exits_with_remediation_hint(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """Malformed auto-discovered reveille.toml exits nonzero with remediation guidance."""
        work_dir = tmp_path_factory.mktemp("malformed_auto_discover")
        output = work_dir / "report.html"
        (work_dir / "reveille.toml").write_text(
            "[report]\ntitle = missing quotes\n",
            encoding="utf-8",
        )
        original = Path(os.getcwd())
        try:
            os.chdir(work_dir)
            result = runner.invoke(
                app,
                ["generate", "--repo", str(e2e_repo), "--output", str(output)],
            )
        finally:
            os.chdir(original)
        assert result.exit_code == ExitCode.CANNOT_RUN
        assert "reveille init --force" in result.output

    def test_format_json_produces_json_file(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """--format json writes a .json file at the output stem path."""
        base = tmp_path_factory.mktemp("format_json")
        output = base / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert (base / "report.json").exists()

    def test_format_csv_produces_csv_file(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """--format csv writes a .csv file at the output stem path."""
        base = tmp_path_factory.mktemp("format_csv")
        output = base / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
                "--format",
                "csv",
            ],
        )
        assert result.exit_code == 0
        assert (base / "report.csv").exists()

    def test_output_path_outside_repo_root_emits_warning(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """An output path outside the repository root emits a warning but succeeds."""
        outside_dir = tmp_path_factory.mktemp("outside_output")
        output = outside_dir / "report.html"
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0
        assert "Warning" in result.output

    def test_output_path_with_traversal_in_stem_is_rejected(
        self,
        e2e_repo: Path,
    ) -> None:
        """An output path containing upward traversal components exits nonzero."""
        result = runner.invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                "../../traversal-report.html",
            ],
        )
        assert result.exit_code == ExitCode.CANNOT_RUN


# ------------------------------------------------------------------
# Init command
# ------------------------------------------------------------------


@pytest.fixture
def init_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary Git repository, made the current directory.

    `reveille init` requires the working directory to be a repository root --
    that is its documented contract. The success-path tests below relied on
    pytest's ambient working directory happening to satisfy it, which is true
    when the suite runs from this checkout and false anywhere else, such as an
    unpacked sdist. They passed for a reason unrelated to what they assert.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)
    return repo


@pytest.mark.e2e
class TestInitCommand:
    """End-to-end tests for `reveille init`."""

    def test_creates_reveille_toml_at_output_path(self, init_cwd: Path) -> None:
        """Default invocation writes reveille.toml to the specified path."""
        dest = init_cwd / "reveille.toml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code == 0
        assert dest.exists()

    def test_output_confirms_written_path(self, init_cwd: Path) -> None:
        """The success message includes the written path."""
        dest = init_cwd / "reveille.toml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert "Configuration file written to" in result.output

    def test_exits_nonzero_when_file_exists_without_force(self, init_cwd: Path) -> None:
        """Non-zero exit when target exists and --force is absent."""
        dest = init_cwd / "reveille.toml"
        dest.write_text("existing", encoding="utf-8")
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code != 0
        assert dest.read_text(encoding="utf-8") == "existing"

    def test_force_flag_overwrites_existing_file(self, init_cwd: Path) -> None:
        """--force succeeds and replaces the existing file."""
        dest = init_cwd / "reveille.toml"
        dest.write_text("stale", encoding="utf-8")
        result = runner.invoke(app, ["init", "--output", str(dest), "--force"])
        assert result.exit_code == 0
        assert dest.read_text(encoding="utf-8") != "stale"

    def test_exits_nonzero_when_parent_directory_missing(self, init_cwd: Path) -> None:
        """Non-zero exit when the parent directory does not exist.

        Runs inside a real repository so the failure is attributable to the
        missing directory. Outside one it exited non-zero for the wrong
        reason, and asserting only on the code could not tell the difference.
        """
        dest = init_cwd / "nonexistent_dir" / "reveille.toml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code != 0
        assert "not a Git repository" not in result.output

    def test_exits_nonzero_outside_git_repository(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-zero exit and no file written when CWD is not a Git repository."""
        non_git = tmp_path / "plain"
        non_git.mkdir()
        dest = non_git / "reveille.toml"
        monkeypatch.chdir(non_git)
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code != 0
        assert not dest.exists()

    def test_mailmap_flag_generates_mailmap_file(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """--mailmap writes a .mailmap file at the repository root."""
        dest = tmp_path_factory.mktemp("mailmap_gen") / "reveille.toml"
        mailmap_path = e2e_repo / ".mailmap"
        original = Path(os.getcwd())
        try:
            os.chdir(e2e_repo)
            result = runner.invoke(app, ["init", "--output", str(dest), "--mailmap"])
            mailmap_exists = mailmap_path.exists()
        finally:
            os.chdir(original)
            mailmap_path.unlink(missing_ok=True)
        assert result.exit_code == 0
        assert mailmap_exists

    def test_mailmap_skipped_when_file_exists_without_force(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """Existing .mailmap is left untouched when --force is absent."""
        dest = tmp_path_factory.mktemp("mailmap_skip") / "reveille.toml"
        mailmap_path = e2e_repo / ".mailmap"
        original_content = "# existing mailmap\n"
        mailmap_path.write_text(original_content, encoding="utf-8")
        original = Path(os.getcwd())
        try:
            os.chdir(e2e_repo)
            result = runner.invoke(app, ["init", "--output", str(dest), "--mailmap"])
            content_after = mailmap_path.read_text(encoding="utf-8")
        finally:
            os.chdir(original)
            mailmap_path.unlink(missing_ok=True)
        assert result.exit_code == 0
        assert content_after == original_content

    def test_mailmap_overwritten_with_force(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """--force replaces an existing .mailmap with the generated template."""
        dest = tmp_path_factory.mktemp("mailmap_force") / "reveille.toml"
        mailmap_path = e2e_repo / ".mailmap"
        mailmap_path.write_text("# stale content\n", encoding="utf-8")
        original = Path(os.getcwd())
        try:
            os.chdir(e2e_repo)
            result = runner.invoke(app, ["init", "--output", str(dest), "--mailmap", "--force"])
            content_after = mailmap_path.read_text(encoding="utf-8")
        finally:
            os.chdir(original)
            mailmap_path.unlink(missing_ok=True)
        assert result.exit_code == 0
        assert content_after != "# stale content\n"

    def test_mailmap_flag_absent_does_not_generate_mailmap(
        self,
        e2e_repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """Omitting --mailmap does not create a .mailmap file."""
        dest = tmp_path_factory.mktemp("mailmap_absent") / "reveille.toml"
        original = Path(os.getcwd())
        try:
            os.chdir(e2e_repo)
            result = runner.invoke(app, ["init", "--output", str(dest)])
        finally:
            os.chdir(original)
        assert result.exit_code == 0
        assert not (e2e_repo / ".mailmap").exists()


# ------------------------------------------------------------------
# Exit code contract
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestExitCodeContract:
    """Tests for the documented exit code contract.

    The distinction that matters to a CI consumer is between a negative
    answer, which may be an acceptable state to record, and an inability
    to answer, which is a broken pipeline step.
    """

    def test_codes_have_their_documented_values(self) -> None:
        """The numbers are the contract; changing one breaks callers."""
        assert ExitCode.SUCCESS == 0
        assert ExitCode.NEGATIVE == 1
        assert ExitCode.CANNOT_RUN == 2

    def test_validate_succeeds_on_a_repository_with_commits(self, e2e_repo: Path) -> None:
        result = CliRunner().invoke(app, ["validate", "--repo", str(e2e_repo)])
        assert result.exit_code == ExitCode.SUCCESS

    def test_validate_returns_negative_for_a_repository_with_no_commits(
        self, tmp_path: Path
    ) -> None:
        """A readable repository with an unborn HEAD is a negative answer.

        Distinct from a path that is not a repository at all, which is an
        inability to answer. Separating these is the point of the contract.
        """
        empty = tmp_path / "empty_repo"
        empty.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=empty, check=True, capture_output=True)
        result = CliRunner().invoke(app, ["validate", "--repo", str(empty)])
        assert result.exit_code == ExitCode.NEGATIVE

    def test_validate_cannot_run_on_a_path_that_is_not_a_repository(self, tmp_path: Path) -> None:
        plain = tmp_path / "not_a_repo"
        plain.mkdir()
        result = CliRunner().invoke(app, ["validate", "--repo", str(plain)])
        assert result.exit_code == ExitCode.CANNOT_RUN

    def test_the_two_failure_modes_are_distinguishable(self, tmp_path: Path) -> None:
        """The finding this contract exists to resolve.

        Before, 'not a repository' and 'repository has no commits' both
        exited 1 and no CI job could tell them apart.
        """
        empty = tmp_path / "empty"
        empty.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=empty, check=True, capture_output=True)
        plain = tmp_path / "plain"
        plain.mkdir()

        runner = CliRunner()
        no_commits = runner.invoke(app, ["validate", "--repo", str(empty)]).exit_code
        not_a_repo = runner.invoke(app, ["validate", "--repo", str(plain)]).exit_code
        assert no_commits != not_a_repo

    def test_generate_returns_negative_for_an_empty_analysis_window(
        self, e2e_repo: Path, tmp_path: Path
    ) -> None:
        """A window containing no commits is an answer, not a failure."""
        result = CliRunner().invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(tmp_path / "report.html"),
                "--since",
                "1990-01-01",
                "--until",
                "1990-12-31",
            ],
        )
        assert result.exit_code == ExitCode.NEGATIVE


@pytest.mark.e2e
class TestVerboseFlag:
    """Tests for --verbose, which must be purely additive."""

    def test_verbose_emits_diagnostics_to_stderr(self, e2e_repo: Path, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(tmp_path / "r.html"),
                "--verbose",
            ],
        )
        assert result.exit_code == ExitCode.SUCCESS
        assert "DEBUG" in result.output

    def test_default_invocation_emits_no_diagnostics(self, e2e_repo: Path, tmp_path: Path) -> None:
        """Adding the flag must not change output for anyone not using it."""
        result = CliRunner().invoke(
            app,
            ["generate", "--repo", str(e2e_repo), "--output", str(tmp_path / "r.html")],
        )
        assert result.exit_code == ExitCode.SUCCESS
        assert "DEBUG" not in result.output

    def test_importing_reveille_installs_no_log_handler(self) -> None:
        """A library must not impose logging policy on its host.

        Run in a clean interpreter: a --verbose test elsewhere in this
        process legitimately attaches a handler, so asserting in-process
        would test the test suite rather than the import.
        """
        probe = (
            "import logging, reveille; "
            "print(all(isinstance(h, logging.NullHandler) "
            "for h in logging.getLogger('reveille').handlers))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "True", result.stdout

    def test_repeated_configuration_attaches_one_handler(self) -> None:
        """Configuring twice must not duplicate every diagnostic line.

        Asserted against the handler set rather than captured output:
        `StreamHandler` binds `sys.stderr` at construction and CliRunner
        replaces that stream per invocation, so an output-based assertion
        would measure the test harness rather than the property.
        """
        import logging

        from reveille.cli import _configure_logging

        package_logger = logging.getLogger("reveille")
        original_handlers = list(package_logger.handlers)
        original_level = package_logger.level
        try:
            package_logger.handlers = [logging.NullHandler()]
            _configure_logging(verbose=True)
            _configure_logging(verbose=True)
            attached = [
                h
                for h in package_logger.handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
            ]
            assert len(attached) == 1
        finally:
            package_logger.handlers = original_handlers
            package_logger.setLevel(original_level)

    def test_without_verbose_a_handler_is_attached_at_warning_level(self) -> None:
        """Warnings are not diagnostics and must not need a flag.

        This asserted the opposite until v0.8.0: no handler at all without
        `--verbose`, which meant `--exclude-author` matching nobody was
        completely silent. A privacy filter that silently did nothing looked
        exactly like one that worked.
        """
        import logging

        from reveille.cli import _configure_logging

        package_logger = logging.getLogger("reveille")
        original_handlers = list(package_logger.handlers)
        original_level = package_logger.level
        try:
            package_logger.handlers = [logging.NullHandler()]
            _configure_logging(verbose=False)

            streams = [
                h
                for h in package_logger.handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
            ]
            assert len(streams) == 1
            assert package_logger.level == logging.WARNING
        finally:
            package_logger.handlers = original_handlers
            package_logger.setLevel(original_level)

    def test_a_warning_reaches_stderr_without_verbose(self, e2e_repo: Path, tmp_path: Path) -> None:
        """The case this exists for: an exclusion that matched nothing."""
        result = CliRunner().invoke(
            app,
            [
                "generate",
                "--repo",
                str(e2e_repo),
                "--output",
                str(tmp_path / "r.html"),
                "--exclude-author",
                "nobody@nowhere.example",
            ],
        )

        assert result.exit_code == ExitCode.SUCCESS
        assert "matched no commits" in result.output
        assert "DEBUG" not in result.output


# ------------------------------------------------------------------
# Report accessibility
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestReportAccessibility:
    """Structural accessibility assertions on the rendered report.

    The report is distributed to stakeholders and embedded in Confluence,
    which is the context where WCAG 2.1 AA and EN 301 549 are asked about.
    These assert the structures assistive technology depends on survive
    into the output.
    """

    def test_document_declares_a_language(self, default_report_content: str) -> None:
        assert 'lang="en"' in default_report_content

    def test_report_body_is_a_main_landmark(self, default_report_content: str) -> None:
        """Lets a screen-reader user skip navigation straight to content."""
        assert "<main" in default_report_content

    def test_table_column_headers_declare_scope(self, default_report_content: str) -> None:
        """Without scope, a screen reader cannot announce which column a cell belongs to.

        Asserted as a property rather than a count. The count was `>= 10`,
        which was the ranked table's column total; when the ranking became
        opt-in the default table lost three columns and the test failed
        without anything being wrong. What matters is that no column header
        lacks a scope, whichever columns are present.
        """
        import re

        thead = re.findall(r"<thead>(.*?)</thead>", default_report_content, re.DOTALL)
        assert thead, "no table header found in the report"
        headers = [th for block in thead for th in re.findall(r"<th\b[^>]*>", block)]
        assert headers, "table header contains no header cells"
        assert all('scope="col"' in th for th in headers), (
            f"column headers missing scope: {[th for th in headers if 'scope=' not in th]}"
        )

    def test_table_row_headers_declare_scope(self, default_report_content: str) -> None:
        assert 'scope="row"' in default_report_content

    def test_table_has_a_caption(self, default_report_content: str) -> None:
        """The caption names the table when navigating between tables."""
        assert "<caption" in default_report_content

    def test_every_chart_has_a_text_alternative(self, default_report_content: str) -> None:
        """Plotly renders to SVG, which conveys nothing to assistive technology.

        Each chart container is exposed as a single labelled image rather
        than a tree of meaningless shapes.
        """
        assert default_report_content.count('role="img"') >= 7

    def test_heatmap_contributor_filter_is_labelled(self, default_report_content: str) -> None:
        """A bare select announces only its value, never its purpose."""
        assert "Filter the activity heatmap by contributor" in default_report_content

    def test_summary_cards_expose_a_coherent_phrase(self, default_report_content: str) -> None:
        """The value and its label are separate elements visually.

        Read literally, that gives a screen reader an orphaned number
        followed by an orphaned noun. The visually hidden text restores
        the association.
        """
        assert "visually-hidden" in default_report_content
        assert "Total Commits:" in default_report_content

    def test_reduced_motion_preference_is_honoured(self, default_report_content: str) -> None:
        """WCAG 2.1 SC 2.3.3, set at the OS level by affected readers."""
        assert "prefers-reduced-motion" in default_report_content

    def test_report_still_loads_no_external_resources(self, default_report_content: str) -> None:
        """The offline guarantee must survive every accessibility change.

        No stylesheet link, script src, or image src may reference a
        remote host. Attribution URLs inside the vendored Plotly bundle
        are inert string literals for chart types Reveille never renders.
        """
        assert not re.search(r"<link[^>]+href=[\"']https?://", default_report_content)
        assert not re.search(r"<script[^>]+src=[\"']https?://", default_report_content)
        assert not re.search(r"<img[^>]+src=[\"']https?://", default_report_content)

    def test_no_markup_or_stylesheet_fetches_a_remote_resource(
        self,
        default_report_content: str,
    ) -> None:
        """The offline guarantee, asserted as a property rather than a tag list.

        The test above names three tags. That list is only as good as
        whoever remembers to extend it: an ``<iframe src>``, an ``<object
        data>``, a ``poster=``, or a CSS ``@import`` would each forfeit
        the guarantee while leaving it green.

        ``<script>`` bodies are excluded because the vendored Plotly
        bundle carries map-tile and attribution URLs as string literals,
        for trace types Reveille never emits. ``<style>`` bodies are
        deliberately *not* excluded: a stylesheet is applied, so its
        ``url()`` and ``@import`` rules fetch.

        ``href`` is checked on ``<link>`` only. An ``<a href>`` to a
        remote page navigates on a click; it does not load anything into
        the report, and flagging it would make this guard cry wolf.
        """
        class _TagStripper(HTMLParser):
            def __init__(self, blocked: set[str]) -> None:
                super().__init__(convert_charrefs=False)
                self._blocked = {name.lower() for name in blocked}
                self._depth = 0
                self.parts: list[str] = []

            def handle_starttag(self, tag: str, attrs) -> None:
                if tag.lower() in self._blocked:
                    self._depth += 1
                elif self._depth == 0:
                    self.parts.append(self.get_starttag_text())

            def handle_endtag(self, tag: str) -> None:
                if tag.lower() in self._blocked and self._depth > 0:
                    self._depth -= 1
                elif self._depth == 0:
                    self.parts.append(f"</{tag}>")

            def handle_startendtag(self, tag: str, attrs) -> None:
                if self._depth == 0 and tag.lower() not in self._blocked:
                    self.parts.append(self.get_starttag_text())

            def handle_data(self, data: str) -> None:
                if self._depth == 0:
                    self.parts.append(data)

            def handle_comment(self, data: str) -> None:
                if self._depth == 0:
                    self.parts.append(f"<!--{data}-->")

            def handle_decl(self, decl: str) -> None:
                if self._depth == 0:
                    self.parts.append(f"<!{decl}>")

            def handle_pi(self, data: str) -> None:
                if self._depth == 0:
                    self.parts.append(f"<?{data}>")

        stripper = _TagStripper({"script", "style"})
        stripper.feed(default_report_content)
        stripper.close()
        markup = "".join(stripper.parts)

        loaded = re.findall(
            r"""\b(?:src|srcset|poster|data)\s*=\s*["'](?:https?:)?//[^"']*""",
            markup,
        )
        assert loaded == [], f"report markup loads remote resources: {loaded}"

        linked = re.findall(
            r"""<link\b[^>]*\bhref\s*=\s*["'](?:https?:)?//[^"']*""",
            markup,
            re.IGNORECASE,
        )
        assert linked == [], f"report links remote stylesheets: {linked}"

        stylesheets = re.findall(
            r"<style\b[^>]*>(.*?)</style>",
            default_report_content,
            re.DOTALL | re.IGNORECASE,
        )
        assert stylesheets, "the report carries no inline stylesheet"
        css = "\n".join(stylesheets)
        assert "@import" not in css, "an @import in the report CSS fetches at render time"

        remote = [
            reference
            for reference in re.findall(r"""url\(\s*["']?([^)"']+)""", css)
            if reference.startswith(("http://", "https://", "//"))
        ]
        assert remote == [], f"report CSS references remote hosts: {remote}"
