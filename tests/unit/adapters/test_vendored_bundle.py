# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The chart library Reveille ships is the one it pinned, draws every chart, and carries its licences.

Every HTML report embeds the plotly.js cartesian bundle from `reveille/vendor/`
(ADR 0027). A trace type the bundle does not register is drawn as a scatter
without a word: the basic bundle, tried first, turned the commit heatmap into
dots. MIT and BSD-3-Clause both require their notices in every copy, and the
report is a copy.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from markupsafe import escape

from reveille.adapters.renderer import Renderer
from tests.unit.adapters.test_lorenz_chart import _report_data

pytestmark = pytest.mark.unit

_SOURCE = Path(__file__).resolve().parents[3] / "src" / "reveille"
_VENDOR = _SOURCE / "vendor"
_BUNDLE = (_VENDOR / "plotly-cartesian.min.js").read_text(encoding="utf-8")
_PIN = json.loads((_VENDOR / "plotly-cartesian.json").read_text(encoding="utf-8"))
_NOTICES = (_VENDOR / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
_TEMPLATE = (_SOURCE / "templates" / "report.html.j2").read_text(encoding="utf-8")
# Axis types share the `type:` key with traces in the template's script.
_AXIS_TYPES = frozenset({"-", "category", "date", "linear", "log", "multicategory"})


def _registered(bundle: str) -> set[str]:
    return set(re.findall(r'moduleType:"trace",name:"([a-z0-9]+)"', bundle))


def test_the_bundle_is_the_one_pinned() -> None:
    assert hashlib.sha256(_BUNDLE.encode("utf-8")).hexdigest() == _PIN["sha256"]
    assert f"plotly.js (cartesian - minified) v{_PIN['version']}" in _BUNDLE[:200]


def test_every_trace_type_the_report_draws_is_registered() -> None:
    from_template = set(re.findall(r"type:\s*'([a-z0-9]+)'", _TEMPLATE)) - _AXIS_TYPES
    from_python = {"bar", "pie", "scatter"}  # tests/e2e/test_cli.py _ALLOWED_TRACE_TYPES

    assert "heatmap" in from_template, "positive control: the heatmap is drawn in the page"
    assert from_template | from_python <= _registered(_BUNDLE)


# Words every copy of each licence carries, compared with whitespace collapsed.
_LICENCE_WORDING = {
    "MIT": "Permission is hereby granted",
    "BSD-3-Clause": "Redistribution and use in source and binary forms",
    "ISC": "Permission to use, copy, modify, and/or distribute",
    "Zlib": "This software is provided 'as-is'",
    "BlueOak-1.0.0": "Blue Oak Model License",
}


def _sections(notices: str) -> dict[str, str]:
    """Map each `name version, licence` heading to the text under it."""
    parts = re.split(r"\n={72}\n", notices)
    return {parts[i].splitlines()[0]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def test_every_bundled_package_has_its_notice() -> None:
    sections = _sections(_NOTICES)
    assert len(_PIN["bundled_packages"]) > 0
    for package in _PIN["bundled_packages"]:
        heading = f"{package['name']} {package['version']}, {package['license']}"
        assert heading in sections, f"{package['name']} has no notice"
        body = " ".join(sections[heading].split())
        assert _LICENCE_WORDING[package["license"]] in body, f"{heading} lacks its licence text"
        assert "opyright" in body, f"{heading} lacks a copyright line"
    assert f"plotly.js {_PIN['version']} (cartesian bundle, {_PIN['package']}), MIT" in sections


def test_every_package_the_bundle_names_is_traced() -> None:
    """The bundle's own licence block is esbuild's record; the trace must cover it."""
    block = _BUNDLE[_BUNDLE.index("Bundled license information:") :]
    block = block[: block.index("*/\n")]
    named = {
        "/".join(path.split("/")[:2]) if path.startswith("@") else path.split("/")[0]
        for path in re.findall(r"^([@a-z0-9._/-]+\.js):$", block, re.MULTILINE)
    }
    traced = {package["name"] for package in _PIN["bundled_packages"]}

    assert {"assert", "safe-buffer"} <= named, "positive control: polyfills esbuild bundled"
    assert named <= traced


def test_the_report_carries_the_notices(tmp_path: Path) -> None:
    Renderer().render(_report_data([3, 1]), tmp_path / "r.html")
    html = (tmp_path / "r.html").read_text(encoding="utf-8")

    assert str(escape(_NOTICES)) in html
    assert "<summary>Third-party licences</summary>" in html
