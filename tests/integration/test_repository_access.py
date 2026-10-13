# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Repositories Git reads differently are answered, or refused; never "no commits".

Both cases below used to report "contains no commits" with exit 1, a confident
negative answer about a repository that has commits.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_WHO = {
    "GIT_AUTHOR_NAME": "Ana",
    "GIT_AUTHOR_EMAIL": "ana@e.test",
    "GIT_COMMITTER_NAME": "Ana",
    "GIT_COMMITTER_EMAIL": "ana@e.test",
}


def _repo(path: Path, *init: str) -> Path:
    path.mkdir()
    env = {**os.environ, **_WHO}
    subprocess.run(["git", "init", "-q", "-b", "main", *init], cwd=path, check=True)
    for name in ("a.txt", "b.txt"):
        (path / name).write_text(name, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-qm", name],
            cwd=path,
            check=True,
            env=env,
        )
    return path


def test_a_repository_owned_by_someone_else_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "r")
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "safe.directory" in result.stderr
    assert "no commits" not in result.stderr


def test_a_sha256_repository_cannot_run_yet(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r", "--object-format=sha256")

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "SHA-256" in result.stderr
    assert "no commits" not in result.stderr


def test_a_git_older_than_the_floor_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every read passes `--end-of-options` (Git 2.24); older Git would fail each one obscurely."""
    from reveille.adapters.git_reader import GitReader

    repo = _repo(tmp_path / "r")
    monkeypatch.setattr(GitReader, "_git_version", lambda self: (2, 20))

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "Git 2.24 or newer" in result.stderr
    assert "2.20" in result.stderr


def test_a_named_branch_is_read_when_head_has_no_commits(tmp_path: Path) -> None:
    """An orphan checkout leaves HEAD unborn; `--branch main` still names commits."""
    repo = _repo(tmp_path / "r")
    subprocess.run(["git", "switch", "-q", "--orphan", "fresh"], cwd=repo, check=True)

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--branch", "main"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "2 commits" in result.stdout


@pytest.mark.parametrize("value", ["HEAD~1..main", "main^!", "main^@", "HEAD...main"])
def test_branch_names_one_commit_not_a_range(tmp_path: Path, value: str) -> None:
    """A range given as a branch narrowed the history while the report said "branch";
    an auto-discovered reveille.toml could set it."""
    repo = _repo(tmp_path / "r")

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--branch", value])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "does not name a commit" in result.stderr
