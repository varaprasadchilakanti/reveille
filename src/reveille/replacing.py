# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Write a file by replacing its name, not by writing into the existing file.

Used by the renderer (reports) and `init` (config and `.mailmap`). Standard
library only.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
from pathlib import Path

from reveille.git_directory import (
    holds_a_git_directory,
    holds_a_git_directory_open,
    is_a_linked_worktree,
    is_a_linked_worktree_open,
)

#: Whether files can be created and moved relative to an open directory (not Windows).
_DIRECTORY_DESCRIPTORS = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    # `os.replace` takes the same descriptors as `os.rename`, which the set lists.
    and {os.open, os.stat, os.unlink, os.rename} <= os.supports_dir_fd
)

#: How the working directory is opened: `O_PATH` (Linux) needs no list permission.
_SEARCH_ONLY = getattr(os, "O_PATH", os.O_RDONLY)


def write_replacing(path: Path, text: str, *, encoding: str) -> None:
    """Write `text` to a new file and move it over `path`.

    Replacing the name leaves other hard links to the old file untouched. A new
    file is owner-only (0o600), since reports and a filled-in `.mailmap` name
    people; an existing file keeps its mode, and a read-only one is refused, as
    the shell's `>` refuses it. The text is fsynced before the move; the
    temporary file is removed on failure.

    Every step works in the directory opened once, so a directory swapped for a
    link or a Git directory after the check is not written into. On Windows the
    path is checked again, then used.

    Args:
        path: The resolved output path.
        text: What to write. Newlines are written as given.
        encoding: The text encoding, `utf-8-sig` for a CSV with a BOM.

    Raises:
        OSError: If the file cannot be created, written or moved; the path is
            not a regular file or is read-only; its directory is now a link; or
            it is inside a Git directory. The error names `path`, not the
            temporary file.
    """
    if not _DIRECTORY_DESCRIPTORS:  # Windows
        if _in_a_git_directory_by_path(path.parent):
            raise OSError(errno.EPERM, "inside a Git directory", str(path))
        _write_in(None, path, path.with_name(_temporary_name(path)), text, encoding)
        return
    directory = os.open(path.parent, _SEARCH_ONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if _in_a_git_directory(directory):
            raise OSError(errno.EPERM, "inside a Git directory", str(path))
        _write_in(directory, Path(path.name), Path(_temporary_name(path)), text, encoding)
    finally:
        os.close(directory)


def _temporary_name(path: Path) -> str:
    """Return a name beside `path` no other run picks."""
    return f".{path.name}.{secrets.token_hex(8)}.tmp"


def _write_in(directory: int | None, name: Path, temporary: Path, text: str, encoding: str) -> None:
    """Write `temporary` and move it over `name`, both in `directory` (None: as given)."""
    try:
        mode = os.stat(name, dir_fd=directory).st_mode
    except FileNotFoundError:
        kept_mode: int | None = None
    else:
        if not stat.S_ISREG(mode):  # replaced, a device node or a pipe would be gone
            raise OSError(
                errno.EINVAL,
                "not a regular file (a directory, a device, a named pipe or a socket)",
                str(name),
            )
        kept_mode = stat.S_IMODE(mode)
        if not kept_mode & stat.S_IWUSR:
            raise PermissionError(
                errno.EACCES, "read-only; make it writable to replace it", str(name)
            )
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory
        )
    except OSError as exc:
        raise type(exc)(exc.errno, exc.strerror, str(name)) from exc
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            # Windows before Python 3.13 cannot chmod a descriptor; its only mode
            # bit is read-only, refused above, so nothing is lost.
            if kept_mode is not None and os.chmod in os.supports_fd:
                os.chmod(handle.fileno(), kept_mode)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        raise


def _in_a_git_directory_by_path(directory: Path) -> bool:
    """Return whether `directory`, or one above it, is a Git directory, by path.

    For Windows, where directories cannot be held open; a directory renamed
    during the walk is not seen.

    Args:
        directory: A resolved directory.

    Returns:
        True when it, or a directory above it, is one.
    """
    for current in (directory, *directory.parents):
        if holds_a_git_directory(current):
            return True
        if is_a_linked_worktree(current):
            return False  # a checkout, though Git may keep it inside its directory
    return False


def _in_a_git_directory(directory: int) -> bool:
    """Return whether the open `directory`, or one above it, is a Git directory.

    As Git judges one (`reveille.git_directory`), stopping at the root of a
    linked worktree. Walked through `..` from the open directory, so a rename
    meanwhile cannot hide one.

    Args:
        directory: An open directory.

    Returns:
        True when it, or a directory above it, is one.
    """
    current = os.dup(directory)
    try:
        while True:
            if holds_a_git_directory_open(current):
                return True
            if is_a_linked_worktree_open(current):
                return False  # a checkout, though Git may keep it inside its directory
            parent = os.open("..", _SEARCH_ONLY | os.O_DIRECTORY, dir_fd=current)
            here, above = os.fstat(current), os.fstat(parent)
            os.close(current)
            current = parent
            if (here.st_dev, here.st_ino) == (above.st_dev, above.st_ino):
                return False  # the root is its own parent
    finally:
        os.close(current)
