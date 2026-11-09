# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0
"""AGENTS.md names commands that exist and files that are tracked."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_TEXT = (_ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_each_make_command_is_a_target() -> None:
    targets = set(re.findall(r"(?m)^([a-z][a-z-]*):", (_ROOT / "Makefile").read_text("utf-8")))
    named = set(re.findall(r"`make ([a-z-]+)`", _TEXT))

    assert "ci" in named, "positive control: the file names a make command"
    assert named <= targets, f"not Makefile targets: {sorted(named - targets)}"


def test_each_link_is_a_tracked_file() -> None:
    links = re.findall(r"\]\(([^)#]+)", _TEXT)

    assert links, "positive control: the file has links"
    for link in links:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", link], cwd=_ROOT, capture_output=True
        )
        assert tracked.returncode == 0, f"{link} is not tracked"
