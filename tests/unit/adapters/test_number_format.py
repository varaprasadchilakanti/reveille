# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""One number, one spelling, everywhere it appears.

A 30,000-commit report printed "30000" on its card and "30,000" in its
findings, "17497" above a bar and "1000" on an axis beside labels reading
"1,594". The change-size chart counted commits that change no line under
"1-9", and mixed "1k-4,999" with "5,000+".
"""

from __future__ import annotations

import datetime
import json
import re

import pytest

from reveille.adapters.renderer import (
    Renderer,
    _build_commit_size_chart,
    _build_hotspot_chart,
)
from reveille.domain.models import Commit, FileStats
from tests.unit.adapters.test_lorenz_chart import _report_data


def _commits(sizes: list[int]) -> list[Commit]:
    return [
        Commit(
            sha=f"{index:040d}",
            author_name="Dev",
            author_email="d@example.com",
            timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
            lines_added=size,
            lines_deleted=0,
        )
        for index, size in enumerate(sizes)
    ]


@pytest.mark.unit
class TestChangeSizeBins:
    def test_labels_share_one_style(self) -> None:
        bar = json.loads(_build_commit_size_chart(_commits([1])))["data"][0]

        assert bar["x"] == [
            "0\u20139",
            "10\u201349",
            "50\u2013199",
            "200\u2013999",
            "1,000\u20134,999",
            "5,000+",
        ]

    def test_a_commit_changing_no_line_is_in_the_first_bin(self) -> None:
        bar = json.loads(_build_commit_size_chart(_commits([0, 0, 5])))["data"][0]

        assert bar["y"][0] == 3

    def test_counts_carry_thousands_separators(self) -> None:
        bar = json.loads(_build_commit_size_chart(_commits([3] * 1500)))["data"][0]

        assert bar["text"][0] == "1,500"


@pytest.mark.unit
class TestNumberAxes:
    def test_a_value_axis_writes_numbers_in_full(self) -> None:
        files = [
            FileStats(path=f"f{i}.py", commits=1, lines_added=i * 900, lines_deleted=0)
            for i in range(1, 6)
        ]
        layout = json.loads(_build_hotspot_chart(files))["layout"]

        assert layout["xaxis"]["separatethousands"] is True
        assert layout["xaxis"]["exponentformat"] == "none"


@pytest.mark.unit
def test_cards_carry_thousands_separators(tmp_path_factory: pytest.TempPathFactory) -> None:
    out = tmp_path_factory.mktemp("cards") / "r.html"
    Renderer().render(_report_data([20000, 10000]), out)
    html = out.read_text(encoding="utf-8")

    assert re.search(r'class="value" aria-hidden="true">30,000<', html)
    assert "Total Commits: 30,000" in html
