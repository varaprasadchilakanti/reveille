# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Write a file by replacing its name, never by writing into the existing file.

Shared by the renderer, which writes reports, and `init`, which writes the
config and `.mailmap` scaffolds. Standard library only.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
from pathlib import Path

#: Whether files can be made and moved relative to an open directory (not on Windows).
_DIRECTORY_DESCRIPTORS = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    # `os.replace` takes the same descriptors as `os.rename`, which the set lists.
    and {os.open, os.stat, os.unlink, os.rename} <= os.supports_dir_fd
)


def write_replacing(path: Path, text: str, *, encoding: str) -> None:
    """Write `text` to a new file and move it over `path`.

    Replacing the name, not writing in place, leaves other hard links to the
    old file untouched. A new file is owner-only (0o600), since reports and a
    filled-in `.mailmap` name people; an existing file keeps its mode, so one
    its owner widened stays widened. The temporary file is removed on failure.

    The directory is opened once, and every step is taken in it: one swapped
    for a link, or for a Git directory, after the path was checked is not
    written into (on Windows the path is used, as it was checked).

    Args:
        path: The resolved output path.
        text: What to write. Newlines are written as given.
        encoding: The text encoding, `utf-8-sig` for a CSV with a BOM.

    Raises:
        OSError: If the file cannot be created, written or moved, the path
            names something other than a regular file, its directory is now a
            link, or it is inside a Git directory.
    """
    if not _DIRECTORY_DESCRIPTORS:  # pragma: no cover - Windows
        _write_in(None, path, path.with_name(_temporary_name(path)), text, encoding)
        return
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
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
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            if kept_mode is not None:
                os.chmod(handle.fileno(), kept_mode)
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        raise


def _in_a_git_directory(directory: int) -> bool:
    """Return whether the open `directory`, or one above it, is a Git directory.

    One holding `HEAD`, `objects` and `refs`, as Git takes it. Walked through
    `..` from the directory itself, so a name changed meanwhile cannot hide one.

    Args:
        directory: An open directory.

    Returns:
        True when it, or a directory above it, holds all three.
    """
    current = os.dup(directory)
    try:
        while True:
            if _holds_a_git_directory(current):
                return True
            parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY, dir_fd=current)
            here, above = os.fstat(current), os.fstat(parent)
            os.close(current)
            current = parent
            if (here.st_dev, here.st_ino) == (above.st_dev, above.st_ino):
                return False  # the root is its own parent
    finally:
        os.close(current)


def _holds_a_git_directory(directory: int) -> bool:
    """Return whether the open `directory` holds a `HEAD` file and `objects` and `refs`."""
    kinds = {"HEAD": stat.S_ISREG, "objects": stat.S_ISDIR, "refs": stat.S_ISDIR}
    for name, kind in kinds.items():
        try:
            if not kind(os.stat(name, dir_fd=directory).st_mode):
                return False
        except OSError:
            return False
    return True
