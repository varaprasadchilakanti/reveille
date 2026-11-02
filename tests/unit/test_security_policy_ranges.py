# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""SECURITY.md states the runtime dependency ranges `pyproject.toml` declares."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_NAMES = {
    "typer": "Typer",
    "gitpython": "GitPython",
    "jinja2": "Jinja2",
    "plotly": "Plotly",
    "pydantic": "Pydantic",
}


def test_each_declared_range_is_stated() -> None:
    declared = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = declared["tool"]["poetry"]["dependencies"]
    policy = " ".join((_ROOT / "SECURITY.md").read_text(encoding="utf-8").split())

    runtime = {name: spec for name, spec in dependencies.items() if name != "python"}
    assert set(runtime) == set(_NAMES), "a runtime dependency SECURITY.md does not name"
    for name, spec in runtime.items():
        assert f"{_NAMES[name]} `{spec}`" in policy, f"{name} {spec}"
