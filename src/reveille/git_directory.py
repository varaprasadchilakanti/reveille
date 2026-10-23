# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Tell a Git directory by its files, as Git does. Standard library only.

Git takes a directory for one when it holds `objects` and `refs` and a `HEAD`
that is a symbolic link into `refs/`, or a file naming a ref under `refs/` or
an object. A `HEAD` linked to a branch only `packed-refs` holds is a dangling
link, and still counts; a file named `HEAD` holding anything else does not.

A linked worktree can be made inside a Git directory (`git -C bare.git worktree
add wt`). Its files are a checkout, not Git's own, so a walk up from them stops
at its root, told by a `.git` file whose Git directory names that file back.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

#: Enough of `HEAD` for `ref: refs/` and a SHA-256 object name.
_HEAD_BYTES = 256
_HEX = frozenset(b"0123456789abcdefABCDEF")
#: Enough of a `.git` or `gitdir` file for the path it holds.
_POINTER_BYTES = 4096


def holds_a_git_directory(directory: Path) -> bool:
    """Return whether `directory` is a Git directory, by its files alone.

    Args:
        directory: A path, not resolved through a link at its end.

    Returns:
        True when it holds `objects`, `refs` and a `HEAD` Git reads.
    """
    return _holds(None, directory)


def holds_a_git_directory_open(directory: int) -> bool:
    """Return whether the open `directory` is a Git directory, by its files alone.

    Args:
        directory: An open directory.

    Returns:
        True when it holds `objects`, `refs` and a `HEAD` Git reads.
    """
    return _holds(directory, Path())


def is_a_linked_worktree(directory: Path) -> bool:
    """Return whether `directory` is the root of a linked worktree that links back.

    Args:
        directory: A path.

    Returns:
        True when its `.git` file names a Git directory whose `gitdir` file
        names that same `.git` file.
    """
    try:
        dot_git = os.stat(directory / ".git", follow_symlinks=False)
        target = directory / _pointer(_read(directory / ".git", None), b"gitdir:")
        back = target / _pointer(_read(target / "gitdir", None), b"")
        linked = os.stat(back)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(dot_git.st_mode) and _same(dot_git, linked)


def is_a_linked_worktree_open(directory: int) -> bool:
    """Return whether the open `directory` is the root of a linked worktree that links back.

    Args:
        directory: An open directory.

    Returns:
        True when its `.git` file names a Git directory whose `gitdir` file
        names that same `.git` file.
    """
    try:
        dot_git = os.stat(".git", dir_fd=directory, follow_symlinks=False)
        target = _pointer(_read(Path(".git"), directory), b"gitdir:")
        git_dir = os.open(target, getattr(os, "O_PATH", 0) | os.O_DIRECTORY, dir_fd=directory)
    except (OSError, ValueError):
        return False
    try:
        linked = os.stat(_pointer(_read(Path("gitdir"), git_dir), b""), dir_fd=git_dir)
    except (OSError, ValueError):
        return False
    finally:
        os.close(git_dir)
    return stat.S_ISREG(dot_git.st_mode) and _same(dot_git, linked)


def _read(name: Path, directory: int | None) -> bytes:
    """Return the start of a regular file, without following a link or waiting on a pipe.

    Raises:
        ValueError: If it is not a regular file.
    """
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=directory,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(name)
        return os.read(descriptor, _POINTER_BYTES)
    finally:
        os.close(descriptor)


def _pointer(text: bytes, prefix: bytes) -> str:
    """Return the path a `.git` or `gitdir` file holds after `prefix`.

    Raises:
        ValueError: If it does not begin with `prefix`, or holds no path.
    """
    if not text.startswith(prefix) or not text[len(prefix) :].strip():
        raise ValueError(text)
    return os.fsdecode(text[len(prefix) :].strip())


def _same(one: os.stat_result, other: os.stat_result) -> bool:
    return (one.st_dev, one.st_ino) == (other.st_dev, other.st_ino)


def _holds(directory: int | None, base: Path) -> bool:
    """Read `base`, relative to `directory` when one is open, as Git's `is_git_directory`."""
    try:
        for name in ("objects", "refs"):
            if not stat.S_ISDIR(os.stat(base / name, dir_fd=directory).st_mode):
                return False
        head = base / "HEAD"
        mode = os.stat(head, dir_fd=directory, follow_symlinks=False).st_mode
        if stat.S_ISLNK(mode):
            return os.readlink(head, dir_fd=directory).startswith("refs/")
        if not stat.S_ISREG(mode):
            return False
    except OSError:
        return False
    try:
        descriptor = os.open(
            head,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory,
        )
        try:
            text = os.read(descriptor, _HEAD_BYTES)
        finally:
            os.close(descriptor)
    except OSError:
        return True  # a HEAD that cannot be read is taken as Git's, so nothing is written there
    if text.startswith(b"ref:"):
        return text[4:].lstrip().startswith(b"refs/")
    return len(text) >= 40 and _HEX.issuperset(text[:40])
