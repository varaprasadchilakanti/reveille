# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Group a JUnit XML report's failures by cause, for a log and an annotation.

Usage: test_failures.py REPORT.xml [--annotate]

Paths, object names and numbers are masked, so one cause is one line. No line
starts with `::`, so none is read as a workflow command. `--annotate` also
prints the summary as one `::error` annotation, readable through the API.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

_MASKS = [
    (re.compile(r"[A-Za-z]:[\\/][^\s'\"]*|/(?:tmp|private|var|home|Users)/[^\s'\"]*"), "<path>"),
    (re.compile(r"\b[0-9a-f]{40,64}\b"), "<sha>"),
    (re.compile(r"\d+"), "<n>"),
]
_EXAMPLES = 3
_WIDTH = 200
#: GitHub truncates an annotation's message near 4 KiB and keeps 10 per step.
_ANNOTATION_BYTES = 4000
_ANNOTATIONS = 10


def summarise(report: str) -> str:
    """Return one line per cause, with its count and a few test ids."""
    causes: dict[str, list[str]] = defaultdict(list)
    for case in ET.parse(report).iter("testcase"):
        for outcome in ("failure", "error"):
            found = case.find(outcome)
            if found is None:
                continue
            text = (found.get("message") or found.text or "").strip()
            lines = [x.strip() for x in text.splitlines() if x.strip()]
            # The first line names the failure; the last often holds the error itself.
            cause = " | ".join(dict.fromkeys(lines[:1] + lines[-1:])) or "(no message)"
            for pattern, mask in _MASKS:
                cause = pattern.sub(mask, cause)
            test = f"{case.get('classname', '').rsplit('.', 1)[-1]}::{case.get('name', '')}"
            causes[f"{outcome}: {cause[:_WIDTH]}"].append(test)
    count = sum(map(len, causes.values()))
    lines = [f"{count} not passed, {len(causes)} cause{'' if len(causes) == 1 else 's'}"]
    for cause, tests in sorted(causes.items(), key=lambda item: -len(item[1])):
        lines.append(f"{len(tests)}x {cause}")
        lines += [f"  - {test}" for test in tests[:_EXAMPLES]]
    return "\n".join(lines)


def _parts(text: str) -> list[str]:
    """Split `text` at line ends into pieces of at most `_ANNOTATION_BYTES`."""
    parts = [""]
    for line in text.splitlines():
        if parts[-1] and len((parts[-1] + line).encode()) >= _ANNOTATION_BYTES:
            parts.append("")
        parts[-1] += line[: _ANNOTATION_BYTES // 2] + "\n"
    return [part.rstrip("\n") for part in parts]


def main(argv: list[str]) -> int:
    """Print the summary; with `--annotate`, also as one GitHub annotation."""
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        text = summarise(argv[1])
    except (OSError, ET.ParseError) as exc:
        text = f"no test report: {exc}"
    print(text)
    if "--annotate" in argv:
        for part in _parts(text)[:_ANNOTATIONS]:
            escaped = part.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title=Test failures::{escaped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
