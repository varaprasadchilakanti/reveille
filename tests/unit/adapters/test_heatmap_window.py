# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The activity heatmap draws the analysis window, not the calendar year.

It drew the whole year: for a window from 29 April to 6 October, four months
before the repository existed and three months of the future were drawn
exactly like days with no commits. With a long window the year buttons ran
off the side of the page, and on a phone the grid shrank to a strip about 25
pixels tall.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from reveille.adapters.renderer import _build_heatmap_data
from reveille.domain.models import Commit
from tests.unit.adapters.test_report_layout import _declarations, rendered  # noqa: F401

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


def _commit(day: datetime.date) -> Commit:
    return Commit(
        sha="0" * 40,
        author_name="Dev",
        author_email="d@example.com",
        timestamp=datetime.datetime(day.year, day.month, day.day, 12, tzinfo=datetime.UTC),
        lines_added=1,
        lines_deleted=0,
    )


@pytest.mark.unit
def test_the_payload_carries_the_window() -> None:
    payload = json.loads(
        _build_heatmap_data(
            [_commit(datetime.date(2026, 5, 1))],
            [],
            datetime.date(2026, 4, 29),
            datetime.date(2026, 10, 6),
        )
    )

    assert payload["since"] == "2026-04-29"
    assert payload["until"] == "2026-10-06"


def _grid(year: int, since: str, until: str, counts: dict[str, int]) -> dict:
    source = _TEMPLATE.read_text(encoding="utf-8")
    function = re.search(r"    function buildYearGrid\(.*?\n    \}\n", source, re.DOTALL)
    assert function, "buildYearGrid is missing from the template"
    script = (
        function.group(0)
        + f"\nprocess.stdout.write(JSON.stringify(buildYearGrid({year}, "
        + f"{json.dumps(counts)}, {json.dumps(since)}, {json.dumps(until)})));\n"
    )
    node = shutil.which("node")
    assert node
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js to run the grid code")
class TestTheGrid:
    def test_spans_only_the_weeks_of_the_window(self) -> None:
        grid = _grid(2026, "2026-04-29", "2026-10-06", {"2026-05-01": 3})

        # Monday 27 April to Sunday 11 October: 24 weeks, not 53.
        assert len(grid["x"]) == 24
        assert grid["x"][0] == "Apr 27"

    def test_days_outside_the_window_are_empty_not_zero(self) -> None:
        grid = _grid(2026, "2026-04-29", "2026-10-06", {"2026-05-01": 3})
        monday, tuesday, wednesday, _, friday = (grid["z"][d][0] for d in range(5))

        assert monday is None and tuesday is None, "27 and 28 April precede the window"
        assert wednesday == 0, "29 April is in the window, with no commit"
        assert friday == 3

    def test_a_full_year_inside_the_window_is_unchanged(self) -> None:
        grid = _grid(2025, "2020-01-01", "2030-01-01", {})

        assert len(grid["x"]) in (52, 53)


@pytest.mark.unit
def test_year_buttons_wrap(rendered: str) -> None:  # noqa: F811
    assert "flex-wrap: wrap" in _declarations(rendered, ".heatmap-year-tabs")


@pytest.mark.unit
def test_a_narrow_screen_scrolls_the_grid_rather_than_shrinking_it(
    rendered: str,  # noqa: F811
) -> None:
    assert "overflow-x: auto" in _declarations(rendered, ".heatmap-scroll")
    assert 'class="chart-container heatmap-scroll"' in rendered
    assert "minWidth" in rendered, "the grid is given a width it cannot shrink below"


@pytest.mark.unit
def test_the_grid_is_not_padded_with_empty_columns() -> None:
    """Square cells with the default `constrain: 'range'` extend the x range
    to fill the width, drawing empty weeks past the end of the window."""
    source = _TEMPLATE.read_text(encoding="utf-8")

    assert re.search(
        r"xaxis:\s*\{ type: 'category', tickangle: -45, constrain: 'domain' \}", source
    )


def _show_latest_weeks(scroll_width: int, client_width: int) -> dict:
    """Run the template's `showLatestWeeks` against a stand-in panel and note."""
    source = _TEMPLATE.read_text(encoding="utf-8")
    function = re.search(r"    function showLatestWeeks\(.*?\n    \}\n", source, re.DOTALL)
    assert function, "showLatestWeeks is missing from the template"
    script = (
        "var note = {hidden: true};\n"
        "var document = {getElementById: function (id) {"
        " return id === 'heatmap-scroll-note' ? note : null; }};\n"
        + function.group(0)
        + f"var panel = {{scrollWidth: {scroll_width}, clientWidth: {client_width}, scrollLeft: 0}};\n"
        + "showLatestWeeks({parentNode: panel});\n"
        + "process.stdout.write(JSON.stringify({scrollLeft: panel.scrollLeft, hidden: note.hidden}));\n"
    )
    node = shutil.which("node")
    assert node
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js to run the panel code")
class TestAPanelThatScrollsOpensOnTheLatestWeek:
    """On a phone the grid opened on its oldest weeks, the recent ones off
    screen, and an overlay scrollbar gave no sign that there was more."""

    def test_an_overflowing_panel_scrolls_to_its_end_and_says_so(self) -> None:
        assert _show_latest_weeks(scroll_width=600, client_width=350) == {
            "scrollLeft": 600,
            "hidden": False,
        }

    def test_a_panel_that_fits_stays_put_and_says_nothing(self) -> None:
        assert _show_latest_weeks(scroll_width=900, client_width=900) == {
            "scrollLeft": 0,
            "hidden": True,
        }


@pytest.mark.unit
def test_the_scroll_note_is_hidden_until_the_grid_overflows(rendered: str) -> None:  # noqa: F811
    """Without JavaScript there is no grid to scroll, so the note must not show."""
    assert re.search(r'<p id="heatmap-scroll-note"[^>]*\bhidden\b', rendered)


@pytest.mark.unit
def test_paper_does_not_say_scroll(rendered: str) -> None:  # noqa: F811
    from tests.unit.adapters.test_report_layout import _print_rule

    assert "display: none" in _print_rule(rendered, ".heatmap-scroll-note")
