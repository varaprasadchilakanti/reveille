# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0
"""Every test the ADR index or an ADR's Confirmation names exists."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ADR = Path(__file__).resolve().parents[2] / "docs" / "adr"
_TEST = re.compile(r"`(test_\w+\.py)(?:::(test_\w+))?`")
_ROW = re.compile(r"^\| \[(\d{4})\]\(.*\| ([^|]+) \| ([^|]+) \|$")


def _rows() -> dict[str, tuple[str, str]]:
    text = (_ADR / "README.md").read_text(encoding="utf-8")
    return {m[1]: (m[2], m[3]) for line in text.splitlines() if (m := _ROW.match(line))}


def _confirmations() -> list[tuple[str, str]]:
    found = []
    for record in sorted(_ADR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        if int(record.name[:4]) >= 32:
            line = re.search(r"(?m)^\*\*Confirmation:\*\*.*$", record.read_text("utf-8"))
            found.append((record.name[:4], line[0] if line else ""))
    return found


def _exists(cell: str) -> bool:
    match = _TEST.search(cell)
    if match is None:
        return False
    file, name = match.groups()
    paths = list((_ADR.parents[1] / "tests").rglob(file))
    return bool(paths) and (
        name is None or any(f"def {name}(" in p.read_text("utf-8") for p in paths)
    )


def test_every_record_is_in_the_index() -> None:
    numbers = {path.name[:4] for path in _ADR.glob("[0-9][0-9][0-9][0-9]-*.md")}

    assert set(_rows()) == numbers


@pytest.mark.parametrize(("number", "row"), sorted(_rows().items()))
def test_the_index_names_a_test_that_exists(number: str, row: tuple[str, str]) -> None:
    status, cell = row
    if cell == "—":
        assert status.startswith("Superseded by"), f"ADR {number} is in force and names no test"
        return
    assert _exists(cell), f"ADR {number}: {cell}"


@pytest.mark.parametrize(("number", "line"), _confirmations())
def test_a_new_record_names_its_confirming_test(number: str, line: str) -> None:
    assert _exists(line), f"ADR {number} has no Confirmation line naming an existing test"
