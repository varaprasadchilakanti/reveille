# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The `Next:` command built from a tag name runs as one argument in a POSIX shell.

Anyone who can push a tag chooses its name, and `state` prints a command with it that a
person or an agent may paste. Each name below is one Git accepts as a tag.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reveille.adapters.renderer import _brief_from

pytestmark = pytest.mark.integration

_NAMES = [
    "v1$(touch${IFS}made)",
    "v1`touch${IFS}made`",
    "v1;touch${IFS}made",
    "v1|touch${IFS}made",
    "v1&&touch${IFS}made",
    "v1>made",
    "v1'quote",
    'v1"quote',
    "v1#comment",
    "v1{a,b}",
    "$HOME",
    "!x",
]


@pytest.mark.parametrize("tag", _NAMES)
def test_the_hint_passes_the_tag_as_one_argument(tmp_path: Path, tag: str) -> None:
    accepted = subprocess.run(
        ["git", "check-ref-format", f"refs/tags/{tag}"], capture_output=True, check=False
    )
    assert accepted.returncode == 0, "the name must be one Git accepts as a tag"

    hint = _brief_from(tag)
    command = hint.replace("reveille brief --from", "printf %s", 1)
    assert command != hint, "positive control: the hint has the prefix replaced"
    shown = subprocess.run(
        ["sh", "-c", command], cwd=tmp_path, capture_output=True, text=True, check=True
    )

    assert shown.stdout in {tag, f"refs/tags/{tag}"}
    assert list(tmp_path.iterdir()) == [], "the shell ran part of the tag name"
