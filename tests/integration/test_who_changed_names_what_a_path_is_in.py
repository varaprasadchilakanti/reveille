# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""When no commit changed a path, `who-changed` says what the path is in.

Every directory on the path that looked like a repository was called "another
repository (a submodule or a nested clone)": `.git` itself, a linked worktree
of the same repository, and the repository read, so `who-changed .` with an
empty window exited 2 instead of 1, and `inner/.` said "'inner' is inside
'inner'".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_EMPTY = ["--since", "2099-01-01", "--until", "2099-12-31"]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("names") / "r"
    path.mkdir()
    _git("init", "-q", "-b", "main", cwd=path)
    (path / "a.txt").write_text("a", encoding="utf-8")
    _git("add", "a.txt", cwd=path)
    _git("commit", "-qm", "a", cwd=path)
    _git("worktree", "add", "-q", "-b", "side", str(path / "wt"), cwd=path)
    _git("init", "-q", str(path / "inner"), cwd=path)
    return path


def _who(repo: Path, path: str, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["who-changed", path, "--repo", str(repo), *args])
    return result.exit_code, " ".join(result.stderr.split())


@pytest.mark.parametrize("path", [".", "./"])
def test_the_repository_itself_with_an_empty_window_is_a_negative_answer(
    repo: Path, path: str
) -> None:
    code, stderr = _who(repo, path, *_EMPTY)

    assert code == ExitCode.NEGATIVE, stderr
    assert "another repository" not in stderr


@pytest.mark.parametrize(
    ("path", "said"),
    [
        (".git/config", "'.git/config' is inside '.git', Git's own directory"),
        (".git", "'.git' is Git's own directory"),
        ("inner/.git/HEAD", "'inner/.git/HEAD' is inside 'inner'"),
    ],
)
def test_git_s_own_directory_is_named_as_that(repo: Path, path: str, said: str) -> None:
    code, stderr = _who(repo, path)

    assert code == ExitCode.CANNOT_RUN, stderr
    assert said in stderr


def test_a_linked_worktree_of_this_repository_is_named_as_that(repo: Path) -> None:
    code, stderr = _who(repo, "wt/a.txt")

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "'wt/a.txt' is inside 'wt', another working tree of this repository" in stderr
    assert f"--repo {repo / 'wt'}" in stderr
    assert "another repository" not in stderr


def test_a_nested_clone_named_whole_is_not_inside_itself(repo: Path) -> None:
    code, stderr = _who(repo, "inner/.")

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "'inner' is another repository (a submodule or a nested clone)" in stderr
    assert "inside 'inner'" not in stderr


def test_a_path_inside_a_nested_clone_is_still_named_another_repository(repo: Path) -> None:
    """Control: the message for another repository is unchanged."""
    code, stderr = _who(repo, "inner/x")

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "'inner/x' is inside 'inner', another repository" in stderr
