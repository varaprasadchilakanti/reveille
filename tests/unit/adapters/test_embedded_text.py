# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Text from a repository reaches the report as data, never as markup.

Two rules. File extensions are sanitised before they reach the extension
chart, because Plotly draws a subset of HTML in labels and a crafted file name
could otherwise put a clickable link into the report. And the chart
specifications escape more than `</`: an HTML comment opener followed by
`<script` in a path, extension or name would otherwise change how the parser
reads the script block and blank every chart.
"""

from __future__ import annotations

import datetime
import json
import re
from html import unescape

import plotly.graph_objects as go
import pytest

from reveille.adapters.renderer import (
    _build_extension_chart,
    _build_heatmap_data,
    _sanitise_chart_label,
    _to_json,
)
from reveille.domain.models import Commit, ContributorStats, FileStats, RankedContributor

_HOSTILE = [
    "a<!--<script",
    "<!--<script>",
    "x</script><script>alert(1)</script>",
    "<SCRIPT",
    "<!-- comment",
]


@pytest.mark.parametrize("text", _HOSTILE)
def test_a_chart_specification_holds_no_angle_bracket(text: str) -> None:
    spec = _to_json(go.Figure(go.Bar(x=[text], y=[1])))

    assert "<" not in spec
    assert json.loads(spec)["data"][0]["x"] == [text], "the text survives as data"


@pytest.mark.parametrize("text", _HOSTILE)
def test_the_heatmap_payload_holds_no_angle_bracket(text: str) -> None:
    stamp = datetime.datetime(2026, 3, 1, 10, tzinfo=datetime.UTC)
    stats = ContributorStats(
        name=text,
        email="a@e.test",
        commit_count=1,
        lines_added=1,
        lines_deleted=0,
        active_days=1,
        first_commit_date=stamp.date(),
        last_commit_date=stamp.date(),
    )
    ranked = [
        RankedContributor(
            stats=stats, composite_score=0.0, percentile=0.0, tier=1, tier_designation="Private"
        )
    ]
    commit = Commit(
        sha="0" * 40,
        author_name=text,
        author_email="a@e.test",
        timestamp=stamp,
        lines_added=1,
        lines_deleted=0,
    )

    payload = _build_heatmap_data([commit], ranked, stamp.date(), stamp.date())

    assert "<" not in payload
    names = [c["name"] for c in json.loads(payload)["contributors"]]
    assert unescape(_sanitise_chart_label(text)) in names, "the page is given the name's text"


def test_an_extension_carries_no_markup_into_the_chart() -> None:
    files = [
        FileStats(
            path='f.<a href="https:2130706441">Click', commits=1, lines_added=9, lines_deleted=0
        ),
        FileStats(
            path='g.<span style="font-size:90px">HUGE', commits=1, lines_added=8, lines_deleted=0
        ),
    ]

    labels = json.loads(_build_extension_chart(files))["data"][0]["x"]

    assert not any(re.search(r"<\s*/?\s*(a|span)\b", label, re.IGNORECASE) for label in labels)
    assert any("click" in label.lower() for label in labels), "the extension is still shown"
