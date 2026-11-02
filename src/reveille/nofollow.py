# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Open a file for reading, refusing a symbolic link at the end of its path.

With `O_NOFOLLOW` the open itself refuses the link. Windows lacks it, so the
path is checked first; a link swapped in between check and open is followed.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


def open_not_following(path: Path, *, dir_fd: int | None = None) -> int:
    """Open `path` read-only without waiting on a pipe, refused when it ends in a link.

    Args:
        path: The file, relative to `dir_fd` when one is given.
        dir_fd: An open directory `path` is relative to, or None.

    Returns:
        The open descriptor.

    Raises:
        OSError: `ELOOP` for a link, or whatever `os.open` raises.
    """
    if not hasattr(os, "O_NOFOLLOW") and stat.S_ISLNK(
        os.stat(path, dir_fd=dir_fd, follow_symlinks=False).st_mode
    ):
        raise OSError(errno.ELOOP, "a symbolic link, not followed", str(path))
    return os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=dir_fd,
    )
