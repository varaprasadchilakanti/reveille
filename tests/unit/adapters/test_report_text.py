# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Small things the report said wrongly, each found by reading a rendered page.

"1 Hold Half the Commits"; backticks printed around `git log`, Markdown
leaking into HTML; "Gini runs 0 (even) to 1.00 ... the maximum is (n-1)/n,
not 1", where rounding produced the very number the sentence denies; a
period written "to" in the header and "—" in the footer; and "Branch: HEAD"
for a detached checkout, which names no branch at all.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import replace

import pytest

from reveille.adapters.renderer import Renderer
from reveille.domain.models import Commit, ReportData
from tests.unit.adapters.test_lorenz_chart import _report_data


def _render(data: ReportData, tmp_path_factory: pytest.TempPathFactory) -> str:
    out = tmp_path_factory.mktemp("text") / "report.html"
    Renderer().render(data, out)
    page = out.read_text(encoding="utf-8")
    # Visible markup only: no scripts, styles or comments, whitespace collapsed.
    page = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", "", page, flags=re.DOTALL)
    return " ".join(page.split())


def _with_commits(data: ReportData) -> ReportData:
    data.commits = [
        Commit(
            sha=f"{index:040d}",
            author_name=f"Dev {index % 2}",
            author_email=f"dev{index % 2}@example.com",
            timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
            + datetime.timedelta(days=index),
            lines_added=5,
            lines_deleted=1,
        )
        for index in range(30)
    ]
    return data


@pytest.mark.unit
class TestTheReportsOwnWords:
    def test_one_contributor_holds(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        text = _render(_report_data([30, 1]), tmp_path_factory)

        assert "Holds Half the Commits" in text

    def test_several_contributors_hold(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        text = _render(_report_data([5, 5, 5, 5]), tmp_path_factory)

        assert "Hold Half the Commits" in text
        assert "Holds Half" not in text

    def test_no_markdown_backticks(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        text = _render(_with_commits(_report_data([15, 15])), tmp_path_factory)

        assert "git log" in text, "positive control: the sentence is present"
        assert "`" not in text

    def test_the_gini_ceiling_is_never_printed_as_one(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        text = _render(_report_data([1] * 300), tmp_path_factory)

        match = re.search(r"Gini runs 0 \(even\) to ([0-9.]+)", text)
        assert match, "the Gini note is missing"
        assert float(match.group(1)) < 1
        assert match.group(1) == "0.996"

    def test_a_small_population_keeps_two_places(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        text = _render(_report_data([3, 1]), tmp_path_factory)

        assert "Gini runs 0 (even) to 0.50," in text

    def test_the_period_is_written_one_way(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        text = _render(_report_data([3, 1]), tmp_path_factory)

        assert "2024-01-01 to 2024-06-01" in text
        assert "2024-01-01 — 2024-06-01" not in text
        assert "2024-01-01 &#8212; 2024-06-01" not in text

    def test_a_detached_head_names_the_commit(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        data = _report_data([3, 1])
        data = replace(
            data,
            metadata=replace(data.metadata, analysed_branch="HEAD"),
            provenance=replace(data.provenance, head_sha="0123456789abcdef" * 2 + "01234567"),
        )
        text = _render(data, tmp_path_factory)

        assert "Branch:</strong> detached HEAD at 0123456" in text


@pytest.mark.unit
class TestTheReportStatesItsLimits:
    """Figures from history can be wrong; the artefact says so where it is read."""

    def test_the_html_carries_the_notice_under_the_header(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        text = _render(_report_data([3, 1]), tmp_path_factory)
        header_end = text.index("</header>")

        assert "check before relying on it for a decision" in text[:header_end]

    def test_the_json_carries_it_too(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        import json

        from reveille.adapters.renderer import Renderer

        payload = json.loads(Renderer().json_text(_report_data([3, 1])))

        assert "check before relying on it for a decision" in payload["notice"]


@pytest.mark.unit
def test_no_caption_runs_past_forty_words(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Captions were written to argue; a reader scanning a chart reads two lines."""
    page = _render(_with_commits(_report_data([15, 15])), tmp_path_factory)
    for caption in re.findall(r'<p class="chart-foot">(.*?)</p>', page, re.DOTALL):
        words = re.sub(r"<[^>]+>", " ", caption).split()
        assert len(words) <= 40, " ".join(words)
