# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A Git directory is told by its files as Git tells one, `HEAD` included.

`HEAD` was taken as "a regular file", so a `HEAD` linked to a branch only
`packed-refs` holds, which Git reads, was missed, and any file named `HEAD`
was taken for one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reveille.git_directory import (
    holds_a_git_directory,
    holds_a_git_directory_open,
    is_a_linked_worktree,
    is_a_linked_worktree_open,
)

pytestmark = pytest.mark.unit


def _layout(path: Path) -> Path:
    (path / "objects").mkdir(parents=True)
    (path / "refs").mkdir()
    return path


def _both(path: Path) -> bool:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        opened = holds_a_git_directory_open(descriptor)
    finally:
        os.close(descriptor)
    assert opened == holds_a_git_directory(path), "the two forms agree"
    return opened


@pytest.mark.parametrize(
    "head",
    [
        "ref: refs/heads/main\n",
        "ref:refs/heads/main",
        "1234567890abcdef1234567890abcdef12345678\n",
        "1234567890ABCDEF1234567890abcdef12345678",
        "a" * 64 + "\n",
    ],
    ids=["ref", "ref-no-space", "sha1", "upper-case", "sha256"],
)
def test_a_head_git_reads_makes_one(tmp_path: Path, head: str) -> None:
    git = _layout(tmp_path / "g")
    (git / "HEAD").write_text(head, encoding="utf-8")

    assert _both(git)


@pytest.mark.parametrize(
    "head",
    ["", "hello\n", "ref: heads/main\n", "1234567890abcdef\n", "g" * 40],
    ids=["empty", "text", "ref-outside-refs", "short-id", "not-hex"],
)
def test_a_head_git_does_not_read_makes_none(tmp_path: Path, head: str) -> None:
    git = _layout(tmp_path / "g")
    (git / "HEAD").write_text(head, encoding="utf-8")

    assert not _both(git)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="links")
def test_a_head_linked_into_refs_counts_though_the_link_dangles(tmp_path: Path) -> None:
    git = _layout(tmp_path / "g")
    (git / "HEAD").symlink_to("refs/heads/main")  # only packed-refs holds it

    assert _both(git)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="links")
def test_a_head_linked_outside_refs_does_not(tmp_path: Path) -> None:
    git = _layout(tmp_path / "g")
    (tmp_path / "elsewhere").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "HEAD").symlink_to(tmp_path / "elsewhere")

    assert not _both(git)


@pytest.mark.parametrize("missing", ["objects", "refs", "HEAD"])
def test_each_of_the_three_is_needed(tmp_path: Path, missing: str) -> None:
    git = _layout(tmp_path / "g")
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    target = git / missing
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink()

    assert not _both(git)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
def test_a_head_that_is_a_pipe_is_not_opened(tmp_path: Path) -> None:
    """Opened, a pipe with no writer would wait for ever."""
    git = _layout(tmp_path / "g")
    os.mkfifo(git / "HEAD")

    assert not _both(git)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads any file")
def test_a_head_that_cannot_be_read_is_taken_as_git_s(tmp_path: Path) -> None:
    """Failing closed: the writer then refuses the directory rather than write in it."""
    git = _layout(tmp_path / "g")
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "HEAD").chmod(0)
    try:
        assert _both(git)
    finally:
        (git / "HEAD").chmod(0o644)


def test_objects_that_is_a_file_makes_none(tmp_path: Path) -> None:
    (tmp_path / "objects").write_text("", encoding="utf-8")
    (tmp_path / "refs").mkdir()
    (tmp_path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    assert _both(tmp_path) is False
    (tmp_path / "objects").unlink()
    (tmp_path / "objects").mkdir()
    assert _both(tmp_path) is True, "positive control: a directory"


def _worktree(tmp_path: Path, dot_git: str, back: str | None) -> Path:
    """A checkout whose `.git` file holds `dot_git`, and a Git directory linking `back`."""
    tree, git_dir = tmp_path / "wt", tmp_path / "store" / "worktrees" / "wt"
    tree.mkdir()
    git_dir.mkdir(parents=True)
    (tree / ".git").write_text(dot_git, encoding="utf-8")
    if back is not None:
        (git_dir / "gitdir").write_text(back, encoding="utf-8")
    return tree


def _linked(path: Path) -> bool:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        opened = is_a_linked_worktree_open(descriptor)
    finally:
        os.close(descriptor)
    assert opened == is_a_linked_worktree(path), "the two forms agree"
    return opened


def test_a_worktree_whose_git_directory_has_no_gitdir_file_is_not_linked(tmp_path: Path) -> None:
    tree = _worktree(tmp_path, f"gitdir: {tmp_path / 'store/worktrees/wt'}\n", None)

    assert _linked(tree) is False
    (tmp_path / "store/worktrees/wt/gitdir").write_text(f"{tree / '.git'}\n", encoding="utf-8")
    assert _linked(tree) is True, "positive control: the back-link written"


def test_a_git_file_naming_no_path_is_not_linked(tmp_path: Path) -> None:
    """An empty path would name the checkout itself, so a `gitdir` there must not count."""
    tree = _worktree(tmp_path, "gitdir:   \n", None)
    (tree / "gitdir").write_text(f"{tree / '.git'}\n", encoding="utf-8")

    assert _linked(tree) is False
