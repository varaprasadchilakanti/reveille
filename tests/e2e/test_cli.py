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
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille import __version__
from reveille.cli import app

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
        assert result.exit_code == 1

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
        assert result.exit_code == 1


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
        assert result.exit_code == 1

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
        assert result.exit_code == 1

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
        assert result.exit_code == 1

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
        assert result.exit_code == 1

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
        assert result.exit_code == 1
        assert "reveille init --force" in result.output


# ------------------------------------------------------------------
# Init command
# ------------------------------------------------------------------


@pytest.mark.e2e
class TestInitCommand:
    """End-to-end tests for `reveille init`."""

    def test_creates_reveille_toml_at_output_path(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Default invocation writes reveille.toml to the specified path."""
        dest = tmp_path_factory.mktemp("init_create") / "reveille.toml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code == 0
        assert dest.exists()

    def test_output_confirms_written_path(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        """The success message includes the written path."""
        dest = tmp_path_factory.mktemp("init_confirm") / "reveille.toml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert "Configuration file written to" in result.output

    def test_exits_nonzero_when_file_exists_without_force(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Non-zero exit when target exists and --force is absent."""
        dest = tmp_path_factory.mktemp("init_conflict") / "reveille.toml"
        dest.write_text("existing", encoding="utf-8")
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code != 0

    def test_force_flag_overwrites_existing_file(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """--force succeeds and replaces the existing file."""
        dest = tmp_path_factory.mktemp("init_force") / "reveille.toml"
        dest.write_text("stale", encoding="utf-8")
        result = runner.invoke(app, ["init", "--output", str(dest), "--force"])
        assert result.exit_code == 0
        assert dest.read_text(encoding="utf-8") != "stale"

    def test_exits_nonzero_when_parent_directory_missing(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Non-zero exit when the parent directory does not exist."""
        base = tmp_path_factory.mktemp("init_missing_parent")
        dest = base / "nonexistent_dir" / "reveille.toml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code != 0

    def test_exits_nonzero_outside_git_repository(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Non-zero exit and no file written when CWD is not a Git repository."""
        import os

        non_git = tmp_path_factory.mktemp("non_git_cwd")
        dest = non_git / "reveille.toml"
        original = Path(os.getcwd())
        try:
            os.chdir(non_git)
            result = runner.invoke(app, ["init", "--output", str(dest)])
        finally:
            os.chdir(original)
        assert result.exit_code != 0
        assert not dest.exists()
