# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A new orphan branch has no commits; the repository's other branches do.

"Contains no commits" said the repository was empty. Exit 1 is kept, since
the branch read has none; the message names a branch that has some.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_COMMANDS = [["summary"], ["brief"], ["who-changed", "a.txt"], ["generate", "-q"]]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args], cwd=repo, check=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("a", encoding="utf-8")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "a")
    _git(path, "checkout", "-q", "--orphan", "fresh")
    return path


def _run(repo: Path, command: list[str], tmp_path: Path) -> tuple[int, str]:
    out = ["-o", str(tmp_path / "r.html")] if command[0] == "generate" else []
    result = CliRunner().invoke(app, [*command, "--repo", str(repo), *out])
    return result.exit_code, " ".join(result.stderr.split())


@pytest.mark.parametrize("command", _COMMANDS, ids=lambda c: c[0])
def test_an_orphan_branch_names_a_branch_with_commits(
    repo: Path, tmp_path: Path, command: list[str]
) -> None:
    code, stderr = _run(repo, command, tmp_path)

    assert code == ExitCode.NEGATIVE, stderr
    assert (
        "The current branch 'fresh' has no commits yet; other branches do. "
        "Name one, for example --branch main." in stderr
    )
    assert "contains no commits" not in stderr


@pytest.mark.parametrize("command", _COMMANDS, ids=lambda c: c[0])
def test_a_repository_with_no_branch_still_contains_no_commits(
    tmp_path: Path, command: list[str]
) -> None:
    """Control: with nothing committed anywhere, the repository is empty."""
    empty = tmp_path / "e"
    empty.mkdir()
    _git(empty, "init", "-q", "-b", "main")

    code, stderr = _run(empty, command, tmp_path)

    assert code == ExitCode.NEGATIVE, stderr
    assert "contains no commits" in stderr


def test_the_branch_it_names_is_read(repo: Path, tmp_path: Path) -> None:
    code, stderr = _run(repo, ["summary", "--branch", "main"], tmp_path)

    assert code == ExitCode.SUCCESS, stderr
