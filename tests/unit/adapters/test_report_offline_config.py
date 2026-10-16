# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The report's charts offer no way to send their data off the machine.

Plotly adds a "Share chart..." button (`sendChartToCloud`) whenever
`showSendToCloud` is true, its default; clicking it posts the chart data,
contributor names included, to cloud.plotly.com. Removing a button by a name
the bundle does not define removes nothing, so each name is checked against the
bundled plotly.js itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import plotly
import pytest

pytestmark = pytest.mark.unit

_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "src" / "reveille" / "templates" / "report.html.j2"
)
_BUNDLE = next(Path(plotly.__file__).parent.rglob("plotly.min.js")).read_text(encoding="utf-8")


def _config() -> str:
    text = _TEMPLATE.read_text(encoding="utf-8")
    start = text.index("var PLOTLY_CONFIG = {")
    return text[start : text.index("};", start)]


def test_every_removed_button_is_one_the_bundle_defines() -> None:
    removed = re.findall(r"'(\w+)'", _config().split("modeBarButtonsToRemove", 1)[1])

    assert removed, "no buttons removed"
    for name in removed:
        assert f'name:"{name}"' in _BUNDLE, f"{name} is not a plotly.js mode-bar button"


def test_sharing_to_plotly_cloud_is_switched_off() -> None:
    assert 'showSendToCloud:{valType:"boolean",dflt:!0' in _BUNDLE, (
        "positive control: the bundle shares by default"
    )
    config = _config()

    assert "showSendToCloud: false" in config
    assert "plotlyServerURL: ''" in config
    assert "'sendChartToCloud'" in config


def test_the_report_refuses_every_network_fetch() -> None:
    """Defence in depth for the offline guarantee: if markup ever reaches a chart again,
    the browser still fetches nothing. The policy comes before anything it governs."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', text)

    assert match, "no Content-Security-Policy"
    directives = dict(d.strip().split(" ", 1) for d in match.group(1).split(";") if d.strip())
    assert directives["default-src"] == "'none'"
    assert directives["connect-src"] == "'none'"
    for name, value in directives.items():
        assert "http" not in value and "*" not in value, f"{name} allows a remote source"
    assert match.start() < text.index("<style>") < text.index("<script>")
