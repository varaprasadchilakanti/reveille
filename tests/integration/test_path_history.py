# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A pathspec must not change which commits exist, only which of them count.

Git simplifies history when given a path: a branch merged without keeping its
changes (`git merge -s ours`) is skipped, though every unscoped figure counts it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _commit(repo: Path, name: str, email: str, message: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "C",
        "GIT_COMMITTER_EMAIL": "c@e.test",
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main` holds `src/a`; branch `side` changed `src/a` and was merged `-s ours`."""
    path = tmp_path / "r"
    (path / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "src" / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "base")
    subprocess.run(["git", "switch", "-qc", "side"], cwd=path, check=True)
    (path / "src" / "a").write_text("side\n", encoding="utf-8")
    _commit(path, "Sid", "sid@e.test", "side change")
    subprocess.run(["git", "switch", "-q", "main"], cwd=path, check=True)
    (path / "src" / "a").write_text("2\n", encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "main change")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=C",
            "-c",
            "user.email=c@e.test",
            "merge",
            "-q",
            "-s",
            "ours",
            "side",
            "-m",
            "merge",
        ],
        cwd=path,
        check=True,
    )
    return path


def test_who_changed_counts_a_commit_on_a_branch_merged_without_its_change(repo: Path) -> None:
    result = CliRunner().invoke(
        app, ["who-changed", "src/a", "--repo", str(repo), "--format", "json"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "sid@e.test" in result.stdout
    assert json.loads(result.stdout)["commits"] == 3


@pytest.fixture
def vendored(tmp_path: Path) -> Path:
    """`base` (src), `vendor only`, `both` (src and vendor), `notes` (a `*.md`-named file)."""
    path = tmp_path / "v"
    (path / "src").mkdir(parents=True)
    (path / "vendor" / "lib").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "src" / "a.py").write_text("1\n", encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "base")
    (path / "vendor" / "lib" / "v.js").write_text("v\n" * 50, encoding="utf-8")
    _commit(path, "Vic", "vic@e.test", "vendor only")
    (path / "src" / "a.py").write_text("2\n", encoding="utf-8")
    (path / "vendor" / "lib" / "v.js").write_text("w\n" * 50, encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "both")
    (path / "*.md").write_text("literal\n", encoding="utf-8")
    (path / "README.md").write_text("readme\n", encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "notes")
    return path


def _generate(repo: Path, *args: str) -> tuple[dict[str, object], str]:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", "json", "-o", "-", *args]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return json.loads(result.stdout), result.stderr


class TestExcludePath:
    def test_a_commit_that_changed_only_excluded_paths_is_not_counted(self, vendored: Path) -> None:
        document, _ = _generate(vendored, "--exclude-path", "vendor")

        assert document["metadata"]["total_commits"] == 3  # type: ignore[index]
        assert "vic@e.test" not in json.dumps(document)

    def test_the_excluded_lines_leave_a_mixed_commit(self, vendored: Path) -> None:
        document, _ = _generate(vendored, "--exclude-path", "vendor")

        ana = next(c for c in document["contributors"] if c["email"] == "ana@e.test")  # type: ignore[union-attr]
        # src/a.py twice (1 + 1 added, 1 deleted), `*.md` and README.md once each.
        assert (ana["lines_added"], ana["lines_deleted"]) == (4, 1)

    def test_the_paths_are_recorded_in_the_provenance(self, vendored: Path) -> None:
        document, _ = _generate(vendored, "--exclude-path", "vendor/", "--exclude-path", "./src")

        filters = document["provenance"]["filters"]  # type: ignore[index]
        assert filters["exclude_paths"] == ["vendor", "src"]

    def test_a_path_is_matched_literally_not_as_a_wildcard(self, vendored: Path) -> None:
        document, _ = _generate(vendored, "--exclude-path", "*.md")

        ana = next(c for c in document["contributors"] if c["email"] == "ana@e.test")  # type: ignore[union-attr]
        # 1 + 1 (src), 50 (vendor), 1 (README.md): only the file named `*.md` goes.
        assert ana["lines_added"] == 53

    def test_a_path_that_matches_nothing_is_named(self, vendored: Path) -> None:
        _, stderr = _generate(vendored, "--exclude-path", "vendr")

        assert "--exclude-path matched no file" in stderr
        assert "vendr" in stderr

    def test_a_path_that_matches_is_not_named(self, vendored: Path) -> None:
        _, stderr = _generate(vendored, "--exclude-path", "vendor")

        assert "matched no file" not in stderr

    def test_a_branch_merged_without_its_change_still_counts(self, repo: Path) -> None:
        (repo / "other").write_text("x\n", encoding="utf-8")
        _commit(repo, "Ana", "ana@e.test", "other")

        document, _ = _generate(repo, "--exclude-path", "other")

        assert "sid@e.test" in json.dumps(document["contributors"])

    @pytest.mark.parametrize("value", ["/etc", "../x", "a/../../b", "", "  ", ".", "a\tb", "C:/x"])
    def test_a_path_git_could_not_match_as_meant_is_refused(
        self, vendored: Path, value: str
    ) -> None:
        result = CliRunner().invoke(
            app,
            [
                "generate",
                "--repo",
                str(vendored),
                "--format",
                "json",
                "-o",
                "-",
                "--exclude-path",
                value,
            ],
        )

        assert result.exit_code == ExitCode.CANNOT_RUN
        assert "--exclude-path" in result.stderr

    def test_the_config_file_takes_a_list(self, vendored: Path) -> None:
        config = vendored / "custom.toml"
        config.write_text('[filters]\nexclude_paths = ["vendor"]\n', encoding="utf-8")

        document, _ = _generate(vendored, "--config", str(config))

        assert document["metadata"]["total_commits"] == 3  # type: ignore[index]

    def test_the_config_file_refuses_a_bare_string(self, vendored: Path) -> None:
        config = vendored / "custom.toml"
        config.write_text('[filters]\nexclude_paths = "vendor"\n', encoding="utf-8")

        result = CliRunner().invoke(
            app, ["generate", "--repo", str(vendored), "--config", str(config), "-o", "-"]
        )

        assert result.exit_code == ExitCode.CANNOT_RUN
        assert "exclude_paths must be a list" in result.stderr

    @pytest.mark.parametrize("fmt", ["text", "markdown"])
    def test_summary_says_what_it_left_out(self, vendored: Path, fmt: str) -> None:
        result = CliRunner().invoke(
            app,
            ["summary", "--repo", str(vendored), "--format", fmt, "--exclude-path", "vendor"],
        )

        assert result.exit_code == ExitCode.SUCCESS, result.stderr
        assert "Not counted, by request:" in result.stdout
        assert "vendor" in result.stdout
        assert "3 commits" in result.stdout

    def test_brief_leaves_the_path_out(self, vendored: Path) -> None:
        result = CliRunner().invoke(
            app,
            [
                "brief",
                "--repo",
                str(vendored),
                "--format",
                "json",
                "--since",
                "2000-01-01",
                "--exclude-path",
                "vendor",
            ],
        )

        assert result.exit_code == ExitCode.SUCCESS, result.stderr
        assert "vendor" not in result.stdout.replace('"exclude_paths"', "")

    def test_the_html_report_states_the_paths(self, vendored: Path, tmp_path: Path) -> None:
        out = tmp_path / "r.html"
        result = CliRunner().invoke(
            app, ["generate", "--repo", str(vendored), "-o", str(out), "--exclude-path", "vendor"]
        )

        assert result.exit_code == ExitCode.SUCCESS, result.stderr
        html = out.read_text(encoding="utf-8")
        assert "Paths not counted:" in html
