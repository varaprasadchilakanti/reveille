# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Write a file by replacing its name, never by writing into the existing file.

Shared by the renderer, which writes reports, and `init`, which writes the
config and `.mailmap` scaffolds. Standard library only.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


def write_replacing(path: Path, text: str, *, encoding: str, new_mode: int = 0o600) -> None:
    """Write `text` to a new file and move it over `path`.

    Replacing the name, not writing in place, leaves other hard links to the
    old file untouched. An existing file keeps its mode; a new one is created
    with `new_mode`, less the umask. The temporary file is removed on failure.

    Args:
        path: The resolved output path.
        text: What to write. Newlines are written as given.
        encoding: The text encoding, `utf-8-sig` for a CSV with a BOM.
        new_mode: The mode for a file that did not exist. The default,
            owner-only, suits a report, since it names people.

    Raises:
        OSError: If the file cannot be created, written or moved.
    """
    try:
        kept_mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        kept_mode = None
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    # Reports pass 0o600; `init` passes 0o644, as its files are meant to be committed.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, new_mode)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        if kept_mode is not None:
            temporary.chmod(kept_mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
