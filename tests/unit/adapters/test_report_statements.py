# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""What the report says about a figure is what the code computed.

Recomputed with plain Git, the figures were right and sentences around them were
not: a share of 0.09% printed as "0%", bins said to double in width that do not,
a data table whose last row came second, and one name listed twice with nothing
to tell the two people apart.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import pytest

from reveille.adapters.renderer import (
    Renderer,
    _accessible_table,
    _build_commit_size_chart,
    _build_lorenz_chart,
)
from reveille.domain.models import CoAuthor, Commit
from reveille.domain.pseudonyms import HIDDEN_DOMAIN
from tests.unit.adapters.report_data import report_data

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


def _commit(index: int, name: str, added: int = 3) -> Commit:
    return Commit(
        sha=f"{index:040d}",
        author_name=name,
        author_email=f"{name.lower().replace('[bot]', '-bot')}@example.com",
        timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        + datetime.timedelta(hours=index * 7),
        lines_added=added,
        lines_deleted=0,
    )


def _render(tmp_path: Path, commits: list[Commit], counts: list[int], **extra: object) -> str:
    data = report_data(counts)
    data.commits = commits
    for key, value in extra.items():
        setattr(data, key, value)
    out = tmp_path / "report.html"
    Renderer().render(data, out)
    return out.read_text(encoding="utf-8")


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


@pytest.mark.unit
class TestASmallShareIsNotRoundedAway:
    """One automated commit in 400 is a share, not none (the rule of 19b7c40)."""

    def test_the_profile_says_under_one_percent(self, tmp_path: Path) -> None:
        commits = [_commit(i, f"Dev {i % 3}") for i in range(399)]
        commits.append(_commit(399, "ci[bot]"))

        html = _render(tmp_path, commits, [133, 133, 133])

        row = re.search(
            r'class="profile-name">\s*Automation.*?<span class="profile-value">(.*?)</span>',
            html,
            re.DOTALL,
        )
        assert row, "the profile has no Automation row"
        assert row.group(1).strip() == "under 1%"

    def test_neither_profile_figure_is_formatted_by_rounding_alone(self) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert "'%.0f'|format(axis." not in template


@pytest.mark.unit
class TestTheChangeSizeNote:
    def test_it_does_not_say_the_bins_double(self) -> None:
        """The edges are 0, 10, 50, 200, 1000 and 5000: widths 10, 40, 150, 800, 4000."""
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert "double in width" not in template

    def test_one_line_is_one_line(self) -> None:
        figure = json.loads(_build_commit_size_chart([_commit(0, "Dev", added=1)]))
        assert figure["layout"]["annotations"][0]["text"] == "median 1 line"


@pytest.mark.unit
class TestTheLorenzTableRunsInOrder:
    def test_rows_rise_from_none_to_everyone(self) -> None:
        """The equality line's two points came first, putting 100% in the second row."""
        table = _accessible_table("lorenz", _build_lorenz_chart([1, 2, 7]))

        shares = [row[0] for row in table["rows"]]
        assert shares == sorted(shares)
        assert shares[0] == 0 and shares[-1] == 100


@pytest.mark.unit
class TestCoAuthorsOfOneName:
    def test_two_people_of_one_name_are_told_apart(self, tmp_path: Path) -> None:
        commits = [_commit(i, f"Dev {i % 3}") for i in range(30)]
        html = _render(
            tmp_path,
            commits,
            [10, 10, 10],
            co_authors_only=[
                CoAuthor("Adam Treat", "adam@one.test", 1),
                CoAuthor("Adam Treat", "treat.adam@two.test", 1),
            ],
        )

        listed = re.search(r"Credited only as co-author:(.*?)Co-authored-by", _text(html))
        assert listed, "the co-author list is missing"
        assert "adam@one.test" in listed.group(1)
        assert "treat.adam@two.test" in listed.group(1)

    def test_hidden_addresses_are_told_apart_by_their_token(self, tmp_path: Path) -> None:
        """Under --hide-emails the address is a token; the domain adds nothing."""
        commits = [_commit(i, f"Dev {i % 3}") for i in range(30)]
        html = _render(
            tmp_path,
            commits,
            [10, 10, 10],
            co_authors_only=[
                CoAuthor("Adam Treat", f"p1a2@{HIDDEN_DOMAIN}", 1),
                CoAuthor("Adam Treat", f"p3b4@{HIDDEN_DOMAIN}", 1),
            ],
        )

        assert "Adam Treat (p1a2) (1), Adam Treat (p3b4) (1)." in _text(html)

    def test_a_name_held_once_shows_no_address(self, tmp_path: Path) -> None:
        commits = [_commit(i, f"Dev {i % 3}") for i in range(30)]
        html = _render(
            tmp_path, commits, [10, 10, 10], co_authors_only=[CoAuthor("Carol", "carol@x.test", 2)]
        )

        assert "Credited only as co-author: Carol (2)." in _text(html)


@pytest.mark.unit
class TestTheFooterKeepsEachDateWhole:
    def test_a_date_does_not_break_across_lines(self, tmp_path: Path) -> None:
        """At 360 px the period wrapped as "2023-03- / 10 to / 2026-05- / 04"."""
        html = _render(tmp_path, [_commit(i, f"Dev {i % 3}") for i in range(30)], [10, 10, 10])

        footer = re.search(r'<footer class="report-footer">(.*?)</footer>', html, re.DOTALL)
        assert footer
        assert re.search(r'<time datetime="2024-01-01">2024-01-01</time>', footer.group(1))
        assert re.search(r'<time datetime="2024-06-01">2024-06-01</time>', footer.group(1))
        assert re.search(r"\.report-footer time \{[^}]*white-space: nowrap", html)
