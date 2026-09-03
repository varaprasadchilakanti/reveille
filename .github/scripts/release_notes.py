#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Derive a GitHub Release title and body from CHANGELOG.md.

The release heading carries the version, the date and the theme:
``## [X.Y.Z] — YYYY-MM-DD — Theme``. That convention exists so the
Release title and the changelog cannot drift; this reads it, so the
title is not retyped at release time either.

Headings written before the convention have no theme. Those degrade to
the bare tag rather than failing, because a past release should not
become unreleasable by a convention introduced after it.

Usage::

    release_notes.py v0.8.0 --title
    release_notes.py v0.8.0 --body
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HEADING = (
    r"^## \[{version}\]\s*[—-]\s*\d{{4}}-\d{{2}}-\d{{2}}"
    r"(?:\s*[—-]\s*(?P<theme>.+?))?\s*$"
)


def _section(changelog: str, version: str) -> tuple[str, str]:
    """Return the (theme, body) for a version, or exit if it is absent.

    Args:
        changelog: The full text of CHANGELOG.md.
        version: A version without its leading ``v``.

    Returns:
        The heading's theme (empty if it has none) and the section body.
    """
    heading = re.compile(_HEADING.format(version=re.escape(version)), re.MULTILINE)
    match = heading.search(changelog)
    if match is None:
        sys.exit(
            f"no CHANGELOG heading for {version}. The release notes are read "
            "from it, so a release cannot be described without one."
        )

    rest = changelog[match.end() :]
    following = re.search(r"^## \[", rest, re.MULTILINE)
    body = rest[: following.start()] if following else rest
    # The template separates sections with a horizontal rule, which is
    # scaffolding for the file rather than part of the notes.
    return (match.group("theme") or "").strip(), body.strip().removeprefix("---").strip()


def main() -> None:
    """Print either the release title or its body."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="the release tag, e.g. v0.8.0")
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--title", action="store_true")
    output.add_argument("--body", action="store_true")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    arguments = parser.parse_args()

    theme, body = _section(
        arguments.changelog.read_text(encoding="utf-8"), arguments.tag.lstrip("v")
    )
    if arguments.title:
        print(f"{arguments.tag} — {theme}" if theme else arguments.tag)
    else:
        print(body)


if __name__ == "__main__":
    main()
