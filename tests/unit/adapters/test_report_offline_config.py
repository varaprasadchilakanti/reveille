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

import pytest

pytestmark = pytest.mark.unit

_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "src" / "reveille" / "templates" / "report.html.j2"
)
_BUNDLE = (_TEMPLATE.parents[1] / "vendor" / "plotly-cartesian.min.js").read_text(encoding="utf-8")


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
    assert match.start() < min(text.index("<style>"), text.index("<script>"))


def test_only_the_reports_own_scripts_may_run(tmp_path: Path) -> None:
    """No 'unsafe-inline': a script or event handler anything else put in the page
    does not run. Each script the page runs is allowed by its own hash."""
    import base64
    import hashlib

    from reveille.adapters.renderer import Renderer
    from tests.unit.adapters.report_data import report_data

    out = tmp_path / "r.html"
    Renderer().render(report_data([3, 1]), out)
    page = out.read_text(encoding="utf-8")
    policy = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert policy
    directives = dict(d.strip().split(" ", 1) for d in policy.group(1).split(";") if d.strip())
    allowed = directives["script-src"].split()

    run = re.findall(r"<script>(.*?)</script>", page, re.DOTALL | re.IGNORECASE)
    assert len(run) == 3, "the theme, the chart library and the report's own script"
    assert sorted(allowed) == sorted(
        f"'sha256-{base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()}'" for s in run
    )
