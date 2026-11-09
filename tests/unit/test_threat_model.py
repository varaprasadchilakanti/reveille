# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0
"""Every test the threat model in SECURITY.md names exists."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_ROW_TEST = re.compile(r"`(test_\w+\.py)(?:::(test_\w+))?`\s*\|\s*$")


def _named_tests() -> list[tuple[str, str | None]]:
    text = (_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    section = text.split("## Threat Model", 1)[1].split("\n## ", 1)[0]
    return [m.groups() for line in section.splitlines() if (m := _ROW_TEST.search(line))]


def test_the_table_names_tests() -> None:
    assert len(_named_tests()) >= 10


@pytest.mark.parametrize(("file", "name"), _named_tests(), ids=lambda v: str(v))
def test_a_named_test_exists(file: str, name: str | None) -> None:
    found = list((_ROOT / "tests").rglob(file))

    assert found, f"{file} is not under tests/"
    if name is not None:
        assert re.search(rf"def {name}\(", found[0].read_text(encoding="utf-8")), f"{file}::{name}"
