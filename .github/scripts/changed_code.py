# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Say whether a pull request changes anything but documentation.

Usage: changed_code.py BASE_SHA

Prints `code=true` or `code=false`, appended to `$GITHUB_OUTPUT` when it is set. Markdown,
`llms.txt` and the PNG and SVG images outside `src/` and `tests/` are documentation; anything else
is code. When Git cannot
list the changed files, the answer is `code=true`: every test runs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# Under src/ or tests/ a Markdown or image file may be shipped or read by a test: code.
_DOCUMENTATION = re.compile(r"^(?!src/|tests/).*\.(md|png|svg)$|^llms\.txt$")


def changes_code(paths: list[str]) -> bool:
    """Return whether any path is not documentation; an empty list changes nothing."""
    return any(not _DOCUMENTATION.search(path) for path in paths)


def _changed(base: str) -> list[str] | None:
    """List the paths changed between `base` and HEAD, or None if Git cannot."""
    # Without --no-renames a file renamed from x.py to x.md is listed as x.md alone.
    command = ["git", "diff", "--no-renames", "--name-only", "-z", "--end-of-options", base, "HEAD"]
    try:
        done = subprocess.run([*command, "--"], capture_output=True, check=True)  # noqa: S603  a list
    except (OSError, subprocess.CalledProcessError):
        return None
    return [os.fsdecode(name) for name in done.stdout.split(b"\0") if name]


def main(argv: list[str]) -> int:
    """Print the answer for the base commit given; exit 2 without one."""
    if len(argv) != 2 or not argv[1]:
        print(__doc__, file=sys.stderr)
        return 2
    paths = _changed(argv[1])
    line = f"code={'true' if paths is None or changes_code(paths) else 'false'}"
    print(line)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as file:
            file.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
