# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Write a file by replacing its name, never by writing into the existing file.

Shared by the renderer, which writes reports, and `init`, which writes the
config and `.mailmap` scaffolds. Standard library only.
"""

from __future__ import annotations

import errno
import os
import secrets
import stat
from pathlib import Path


def write_replacing(path: Path, text: str, *, encoding: str) -> None:
    """Write `text` to a new file and move it over `path`.

    Replacing the name, not writing in place, leaves other hard links to the
    old file untouched. A new file is owner-only (0o600), since reports and a
    filled-in `.mailmap` name people; an existing file keeps its mode, so one
    its owner widened stays widened. The temporary file is removed on failure.

    Args:
        path: The resolved output path.
        text: What to write. Newlines are written as given.
        encoding: The text encoding, `utf-8-sig` for a CSV with a BOM.

    Raises:
        OSError: If the file cannot be created, written or moved, or the path
            names something other than a regular file.
    """
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        kept_mode: int | None = None
    else:
        if not stat.S_ISREG(mode):  # replaced, a device node or a pipe would be gone
            raise OSError(
                errno.EINVAL,
                "not a regular file (a directory, a device, a named pipe or a socket)",
                str(path),
            )
        kept_mode = stat.S_IMODE(mode)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        if kept_mode is not None:
            temporary.chmod(kept_mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
