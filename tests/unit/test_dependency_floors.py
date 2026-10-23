# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The declared floors of runtime dependencies stay above known advisories.

Dependabot refreshes `poetry.lock` but never raises a floor, and `pip install
reveille` keeps an older release already in the environment if the floor allows
it. Each floor below is a release no published advisory affected when it
was set (checked against OSV on 2026-10-13); raise it when a new advisory is
fixed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

_FLOORS = {"gitpython": (3, 2, 1), "jinja2": (3, 1, 6), "pydantic": (2, 4)}


def _floor(constraint: str) -> tuple[int, ...]:
    """Read the lowest version a caret or >= constraint allows."""
    version = constraint.lstrip("^>=~ ").split(",")[0].strip()
    return tuple(int(part) for part in version.split("."))


@pytest.mark.unit
@pytest.mark.parametrize(("name", "minimum"), sorted(_FLOORS.items()))
def test_the_floor_excludes_releases_with_known_advisories(
    name: str, minimum: tuple[int, ...]
) -> None:
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["tool"]["poetry"][
        "dependencies"
    ][name]

    assert _floor(declared) >= minimum, f"{name} {declared} allows a release with an advisory"


@pytest.mark.unit
def test_the_plotly_floor_is_the_release_tested_with_the_embedded_bundle() -> None:
    """Reports embed plotly.js 4.1.1 (ADR 0027); 7.0.0 and 7.1.0 were checked, nothing earlier."""
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["tool"]["poetry"][
        "dependencies"
    ]["plotly"]

    assert _floor(declared) >= (7, 0), f"plotly {declared} allows a release never tested"
