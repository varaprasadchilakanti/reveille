# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`--format line` for state and brief: one line, for a prompt or a status bar.

Counts only: no path, no author. A repository-chosen name cannot break it
onto a second line.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


def _make(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    for name in ("a.txt", "b.txt"):
        (path / name).write_text(name, encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", name)
    _git(path, "tag", "v1", "HEAD~1")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _make(tmp_path / "r")


def _line(repo: Path, *args: str) -> str:
    result = CliRunner().invoke(app, [*args, "--repo", str(repo), "--format", "line"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_state_on_a_clean_tree(repo: Path) -> None:
    assert _line(repo, "state") == f"r: main {_head(repo)}; clean; v1 +1\n"


def test_state_counts_changes_and_stashes_without_paths(repo: Path) -> None:
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    _git(repo, "stash")
    (repo / "b.txt").write_text("changed", encoding="utf-8")
    (repo / "secret-plan.txt").write_text("x", encoding="utf-8")
    (repo / "new.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "new.txt")

    out = _line(repo, "state")

    assert out == f"r: main {_head(repo)}; 1 staged, 1 modified, 1 untracked; 1 stash; v1 +1\n"
    assert "secret-plan" not in out


def test_state_names_an_operation_in_progress(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "side", "HEAD~1")
    (repo / "b.txt").write_text("side", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "side")
    # Expected to stop on a conflict; the identity lets Git get that far.
    subprocess.run(
        ["git", "-c", "user.name=Ana", "-c", "user.email=ana@e.test", "merge", "-q", "main"],
        cwd=repo,
        capture_output=True,
        check=False,
    )

    out = _line(repo, "state")

    assert "; merge in progress; 1 conflicted;" in out


def test_state_before_the_first_commit(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")

    assert _line(path, "state") == "empty: main, no commits yet; clean\n"


def test_brief_in_counts(repo: Path) -> None:
    out = _line(repo, "brief", "--from", "v1")

    assert out == f"r main since v1 to {_head(repo)}: 1 commit by 1 person, 1 file added\n"
    assert "Ana" not in out and "ana@" not in out


def test_a_name_with_a_newline_stays_on_one_line(tmp_path: Path) -> None:
    repo = _make(tmp_path / "x\ny")

    for args in (("state",), ("brief", "--from", "v1")):
        out = _line(repo, *args)
        assert out.count("\n") == 1 and out.endswith("\n"), out
        assert out.startswith("x\\ny"), out


def test_summary_does_not_take_it(repo: Path) -> None:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--format", "line"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "text, json or markdown" in result.stderr
