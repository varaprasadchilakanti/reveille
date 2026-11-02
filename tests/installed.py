# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Find the console script installed beside this interpreter."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows: pip and uv install `.exe`, Poetry a `.cmd`; the bare file is for Git Bash.
_SUFFIXES = (".exe", ".cmd") if os.name == "nt" else ("",)


def installed_command(name: str = "reveille") -> Path | None:
    """Return the runnable `name` beside `sys.executable`, or None."""
    bindir = Path(sys.executable).parent
    return next((bindir / (name + s) for s in _SUFFIXES if (bindir / (name + s)).is_file()), None)
