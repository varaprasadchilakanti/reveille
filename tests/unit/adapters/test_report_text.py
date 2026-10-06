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
from pathlib import Path

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

    def test_every_output_states_the_same_notice(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """One copy: the HTML once carried its own wording, and drifted."""
        import json

        from reveille.adapters.renderer import _NOTICE

        data = _report_data([3, 1])
        notice = re.search(r'<p class="report-notice">(.*?)</p>', _render(data, tmp_path_factory))

        assert notice
        assert notice.group(1).strip() == _NOTICE
        assert json.loads(Renderer().json_text(data))["notice"] == _NOTICE

    def test_paper_is_not_told_the_table_scrolls(self) -> None:
        from reveille.adapters import renderer

        template = (
            Path(renderer.__file__).parent.parent / "templates" / "report.html.j2"
        ).read_text(encoding="utf-8")
        start = template.index("@media print")
        hidden = template[start : template.index("}", template.index("display: none", start))]

        assert ".table-count" in hidden


def _longest_rendering(caption: str) -> int:
    """Words in the longest text a caption can render, over every branch.

    An expression counts as one word; of an `if`'s branches the longest is
    taken, so the bound holds whichever one a report renders.
    """
    caption = re.sub(r"\{#.*?#\}", " ", caption, flags=re.DOTALL)
    stack: list[list[int]] = [[0]]
    for token in re.split(r"(\{%-?.*?-?%\})", caption, flags=re.DOTALL):
        tag = re.match(r"\{%-?\s*(\w+)", token)
        if tag and tag.group(1) == "if":
            stack.append([0])
        elif tag and tag.group(1) in ("elif", "else"):
            stack[-1].append(0)
        elif tag and tag.group(1) == "endif":
            longest = max(stack.pop())
            stack[-1][-1] += longest
        elif not tag:
            text = re.sub(r"<[^>]+>", " ", re.sub(r"\{\{.*?\}\}", " X ", token, flags=re.DOTALL))
            stack[-1][-1] += len(text.split())
    return stack[0][0]


@pytest.mark.unit
def test_no_caption_runs_past_forty_words() -> None:
    """Captions were written to argue; a reader scanning a chart reads two lines.

    Read from the template, not a rendered report: a fixture renders only
    the captions its data reaches, and the hotspot, file-type and area
    captions once went unchecked that way.
    """
    from reveille.adapters import renderer

    template = (Path(renderer.__file__).parent.parent / "templates" / "report.html.j2").read_text(
        encoding="utf-8"
    )
    captions = re.findall(r'<p class="chart-foot">(.*?)</p>', template, re.DOTALL)

    assert len(captions) >= 7, "every chart caption is found"
    for caption in captions:
        assert _longest_rendering(caption) <= 40, " ".join(caption.split())


@pytest.mark.unit
def test_the_word_bound_takes_the_longest_branch() -> None:
    caption = "a b {% if x %}c d e{% else %}f{% endif %} {{ g }}"

    assert _longest_rendering(caption) == 6


@pytest.mark.unit
def test_a_profile_failure_is_a_render_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The docstring promises RenderError; the profile was once outside the wrapper."""
    from reveille.adapters import renderer
    from reveille.exceptions import RenderError

    def broken(*_: object) -> None:
        raise ZeroDivisionError("profile")

    monkeypatch.setattr(renderer, "repository_profile", broken)

    with pytest.raises(RenderError, match="profile"):
        Renderer().html_text(_report_data([3, 1]))
