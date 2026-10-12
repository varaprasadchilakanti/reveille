# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Where a repository keeps Git's own files, in every layout, in process.

The integration tests prove the refusal end to end through the console
script; a subprocess is invisible to coverage, so each layout is also
checked here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reveille.adapters.renderer import _write_replacing
from reveille.cli import _git_directories

pytestmark = pytest.mark.integration


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=path)
    _git(
        "-c",
        "user.name=A",
        "-c",
        "user.email=a@e.test",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "c",
        cwd=path,
    )
    return path


def test_a_working_tree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")

    assert _git_directories(repo) == [(repo / ".git").resolve()]


def test_a_bare_repository(tmp_path: Path) -> None:
    bare = tmp_path / "b.git"
    _git("clone", "-q", "--bare", str(_repo(tmp_path / "r")), str(bare), cwd=tmp_path)

    assert _git_directories(bare) == [bare.resolve()]


def test_a_separate_git_directory(tmp_path: Path) -> None:
    work, store = tmp_path / "work", tmp_path / "store"
    _git("init", "-q", f"--separate-git-dir={store}", str(work), cwd=tmp_path)

    assert _git_directories(work) == [store.resolve()]


def test_a_linked_worktree_names_its_own_and_the_common_directory(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    worktree = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "side", str(worktree), cwd=repo)

    own, common = _git_directories(worktree)

    assert own == (repo / ".git" / "worktrees" / "wt").resolve()
    assert common == (repo / ".git").resolve()


@pytest.mark.parametrize("content", ["not a pointer\n", ""])
def test_a_dot_git_file_that_is_not_a_pointer(tmp_path: Path, content: str) -> None:
    (tmp_path / ".git").write_text(content, encoding="utf-8")

    assert _git_directories(tmp_path) == []


def test_an_unreadable_dot_git_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

    def refuse(*_args: object, **_kwargs: object) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", refuse)

    assert _git_directories(tmp_path) == []


def test_an_empty_commondir_names_one_directory(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    (repo / ".git" / "commondir").write_text("\n", encoding="utf-8")

    assert _git_directories(repo) == [(repo / ".git").resolve()]


def test_a_commondir_naming_itself_is_not_listed_twice(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    (repo / ".git" / "commondir").write_text(".\n", encoding="utf-8")

    assert _git_directories(repo) == [(repo / ".git").resolve()]


def test_a_directory_that_is_no_repository(tmp_path: Path) -> None:
    assert _git_directories(tmp_path) == []


def test_a_failed_move_leaves_no_temporary_and_the_old_file(tmp_path: Path) -> None:
    """A directory cannot be replaced by a file, so `os.replace` raises."""
    target = tmp_path / "report.html"
    target.mkdir()

    with pytest.raises(OSError):
        _write_replacing(target, "<html></html>", encoding="utf-8")

    assert target.is_dir(), "the old entry is untouched"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.html"], "no temporary left"
