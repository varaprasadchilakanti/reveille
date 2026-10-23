# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Tell a Git directory by its files, as Git does. Standard library only.

Git takes a directory for one when it holds `objects` and `refs` and a `HEAD`
that is a symbolic link into `refs/`, or a file naming a ref under `refs/` or
an object. A `HEAD` linked to a branch only `packed-refs` holds is a dangling
link, and still counts; a file named `HEAD` holding anything else does not.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

#: Enough of `HEAD` for `ref: refs/` and a SHA-256 object name.
_HEAD_BYTES = 256
_HEX = frozenset(b"0123456789abcdefABCDEF")


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
