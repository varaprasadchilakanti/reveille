# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The HTML names at most 1,000 people, or `--limit`; the figures count everyone (ADR 0029).

At 100,000 authors the report was 78 MB, 52 MB of it the contributor table. A
report is forwarded, and a list of every name answers no reader's question.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import re

import pytest

from reveille.adapters.renderer import _LORENZ_POINTS, Renderer, _build_lorenz_chart
from reveille.domain.concentration import gini_coefficient, lorenz_curve
from reveille.domain.models import Commit, ReportData

from .test_lorenz_chart import _report_data

pytestmark = pytest.mark.unit


def _rows(html: str) -> int:
    return len(re.findall(r'<span class="contributor-name">', html))


def _heatmap_people(html: str) -> int:
    spec = re.search(r'id="spec-heatmap">(.*?)</script>', html, re.S)
    assert spec, "positive control: the heatmap payload was found"
    return len(json.loads(spec.group(1))["contributors"]) - 1  # less "All Contributors"


def _with_one_commit_each(data: ReportData) -> ReportData:
    """A commit per listed person, so the heatmap has someone to list."""
    commits = [
        Commit(
            sha=f"{i:040x}",
            author_name=r.stats.name,
            author_email=r.stats.email,
            timestamp=datetime.datetime(2024, 3, 1, 12, tzinfo=datetime.UTC),
            lines_added=1,
            lines_deleted=0,
        )
        for i, r in enumerate(data.ranked_contributors)
    ]
    return dataclasses.replace(data, commits=commits)


def _lines_chart_people(html: str) -> int:
    spec = re.search(r'id="spec-contributor_lines">(.*?)</script>', html, re.S)
    assert spec, "positive control: the lines chart was found"
    return len(json.loads(spec.group(1))["data"][0]["x"])


def test_a_long_list_is_cut_at_1000_and_says_so() -> None:
    data = _with_one_commit_each(_report_data(list(range(1, 1201))))

    html = Renderer().html_text(data)

    assert _rows(html) == 1000
    assert _heatmap_people(html) == 1000
    assert _lines_chart_people(html) == 1000
    assert "The first 1,000 of 1,200 listed contributors are shown here" in html


def test_limit_sets_how_many_the_page_names() -> None:
    data = _report_data(list(range(1, 51)))
    data = dataclasses.replace(data, provenance=dataclasses.replace(data.provenance, limit=7))

    html = Renderer().html_text(data)

    assert _rows(html) == 7
    assert "The first 7 of 50 listed contributors" in html


def test_a_short_list_is_whole_and_says_nothing_of_a_cut() -> None:
    html = Renderer().html_text(_report_data(list(range(1, 31))))

    assert _rows(html) == 30
    assert "listed contributors are shown here" not in html


def test_the_gini_is_of_everyone_not_of_the_rows_shown() -> None:
    counts = [1] * 1100 + [500] * 100
    html = Renderer().html_text(_report_data(counts))

    assert f"Gini <b>{gini_coefficient(counts):.2f}</b>" in html
    assert f"{gini_coefficient(counts[:1000]):.2f}" != f"{gini_coefficient(counts):.2f}"


def test_the_lorenz_curve_is_drawn_from_points_of_the_full_curve() -> None:
    counts = [n % 97 + 1 for n in range(5000)]
    full = {(round(x * 100, 4), round(y * 100, 4)) for x, y in lorenz_curve(counts)}

    trace = json.loads(_build_lorenz_chart(counts))["data"][1]
    drawn = list(zip(trace["x"], trace["y"], strict=True))

    assert len(drawn) == _LORENZ_POINTS + 1
    assert drawn[0] == (0, 0) and drawn[-1] == (100, 100)
    assert set(drawn) <= full


def test_a_short_lorenz_curve_keeps_every_point() -> None:
    counts = list(range(1, 101))

    trace = json.loads(_build_lorenz_chart(counts))["data"][1]

    assert len(trace["x"]) == len(lorenz_curve(counts))
