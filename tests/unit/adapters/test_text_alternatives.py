# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A chart's only text alternative is its label, so it must carry data.

`role="img"` makes an SVG's children presentational. Whatever the
`aria-label` says is the whole of what a screen-reader user receives, and
"Bar chart of lines changed grouped by file extension" conveys none of
the numbers. WCAG 2.1 SC 1.1.1 asks for an alternative that serves the
equivalent purpose.

Seven of the report's ten charts had nothing else. v0.8.0 shipped saying
it targets WCAG 2.1 AA while that was true.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

from reveille.adapters.renderer import Renderer, _accessible_table
from tests.unit.adapters.test_lorenz_chart import _report_data

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A report with commits, so every chart has something to draw.

    `_report_data` alone carries no commits, which leaves the timeline,
    the change-size histogram and the heatmap empty -- and an empty chart
    correctly needs no table, which would make these assertions vacuous.
    """
    from reveille.domain.models import Commit

    data = _report_data([12, 7, 3])
    data.commits = [
        Commit(
            sha=f"{index:040d}",
            author_name=f"Dev {index % 3}",
            author_email=f"dev{index % 3}@example.com",
            timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
            + datetime.timedelta(days=index * 3),
            lines_added=10 + index,
            lines_deleted=index,
        )
        for index in range(40)
    ]
    out = tmp_path_factory.mktemp("a11y") / "report.html"
    Renderer().render(data, out)
    return out.read_text(encoding="utf-8")


@pytest.mark.unit
class TestEveryChartHasATabularEquivalent:
    """Not the chart type in prose: the figures."""

    def test_every_drawn_chart_is_followed_by_its_table(self, rendered: str) -> None:
        """Adjacency matters: the table must belong to the chart above it.

        Checked per chart by slicing from its container to the next one,
        so a single table somewhere in the document cannot satisfy them
        all. A chart with no data emits no specification and needs no
        table, so only charts that were actually drawn are required to
        have one.
        """
        drawn = {
            match.group(1)
            for match in re.finditer(r'id="spec-([a-z_]+)"[^>]*>\s*(?!null\s*<)\S', rendered)
        }
        # The heatmap is a daily grid rather than a figure; its label
        # carries the figures instead, asserted separately below.
        drawn.discard("heatmap")
        assert drawn, "no charts with data were rendered"

        containers = list(re.finditer(r'id="chart-([a-z_]+)"', rendered))
        missing = []
        for index, match in enumerate(containers):
            chart = match.group(1)
            if chart not in drawn:
                continue
            stop = containers[index + 1].start() if index + 1 < len(containers) else len(rendered)
            if '<table class="visually-hidden">' not in rendered[match.start() : stop]:
                missing.append(chart)
        assert missing == [], f"charts with no tabular equivalent: {missing}"

    def test_the_heatmap_label_carries_figures(self, rendered: str) -> None:
        """Its payload is a daily grid, so the label is the alternative."""
        label = re.search(r'id="chart-heatmap"[^>]*aria-label="([^"]*)"', rendered).group(1)
        assert re.search(r"\d", label), f"no figures in the heatmap label: {label!r}"
        assert "active days" in label

    def test_the_tables_are_hidden_from_sight_but_not_from_readers(self, rendered: str) -> None:
        """`display: none` would hide it from assistive technology too."""
        assert '<table class="visually-hidden">' in rendered
        hidden = re.search(r"\.visually-hidden\s*\{[^}]*\}", rendered).group(0)
        assert "display: none" not in hidden
        assert "clip" in hidden or "clip-path" in hidden

    def test_every_chart_with_data_gets_a_table(self, rendered: str) -> None:
        """Counted against the charts that have data, not a fixed number.

        A chart with nothing to draw emits no specification and needs no
        table; asserting a count would just encode whichever fixture
        happened to be used.
        """
        drawn = [
            chart
            for chart in re.findall(r'id="spec-([a-z_]+)"[^>]*>\s*(\S)', rendered)
            if chart[1] not in ("n",)  # 'null'
        ]
        tables = re.findall(r'<table class="visually-hidden">(.*?)</table>', rendered, re.DOTALL)
        assert len(tables) >= len([c for c in drawn if c[0] != "heatmap"]) - 1, (
            f"{len(tables)} tables for {len(drawn)} charts with data"
        )

    def test_each_table_has_a_caption_and_column_scopes(self, rendered: str) -> None:
        tables = re.findall(r'<table class="visually-hidden">(.*?)</table>', rendered, re.DOTALL)
        assert tables, "no tabular equivalents were rendered at all"
        for table in tables:
            assert "<caption>" in table
            assert 'scope="col"' in table
            assert 'scope="row"' in table

    def test_a_label_that_names_only_the_chart_type_is_not_left_alone(self, rendered: str) -> None:
        """Every label must point somewhere a reader can get the data."""
        for match in re.finditer(r'id="chart-([a-z_]+)" role="img" aria-label="([^"]*)"', rendered):
            chart, label = match.group(1), match.group(2)
            if chart == "heatmap":
                continue  # its label carries the figures; asserted above
            assert "table" in label.lower(), (
                f"{chart} tells a screen-reader user only what kind of picture it is: {label!r}"
            )


@pytest.mark.unit
class TestTheTableIsReadFromTheChart:
    """A table assembled separately would drift from what is drawn."""

    def test_rows_come_from_the_specification(self) -> None:
        import json

        spec = json.dumps(
            {
                "data": [{"type": "bar", "x": ["a", "b"], "y": [3, 4]}],
                "layout": {},
            }
        )
        table = _accessible_table("extensions", spec)
        assert table["columns"] == ["File type", "Lines changed"]
        assert table["rows"] == [["a", 3], ["b", 4]]

    def test_a_horizontal_bar_has_its_categories_on_y(self) -> None:
        import json

        spec = json.dumps(
            {
                "data": [
                    {
                        "type": "bar",
                        "orientation": "h",
                        "x": [10, 20],
                        "y": ["src/a.py", "src/b.py"],
                    }
                ],
                "layout": {},
            }
        )
        table = _accessible_table("hotspots", spec)
        assert table["rows"] == [["src/a.py", 10], ["src/b.py", 20]]

    def test_several_series_become_several_columns(self) -> None:
        import json

        spec = json.dumps(
            {
                "data": [
                    {"type": "scatter", "name": "Ada", "x": ["w1"], "y": [2]},
                    {"type": "scatter", "name": "Bob", "x": ["w1"], "y": [5]},
                ],
                "layout": {},
            }
        )
        table = _accessible_table("contributor_timeline", spec)
        assert table["columns"] == ["Week", "Ada", "Bob"]
        assert table["rows"] == [["w1", 2, 5]]

    def test_an_empty_chart_yields_no_table(self) -> None:
        assert _accessible_table("timeline", "null") == {}
        assert _accessible_table("timeline", "") == {}

    def test_an_unknown_chart_yields_no_table(self) -> None:
        """A new chart must be given headings deliberately, not guessed."""
        import json

        spec = json.dumps({"data": [{"type": "bar", "x": ["a"], "y": [1]}]})
        assert _accessible_table("something_new", spec) == {}


@pytest.mark.unit
class TestIdentityIsNotCarriedByColourAlone:
    """WCAG 1.4.1. A legend is a key to the colour, not a substitute."""

    def test_each_timeline_series_has_its_own_dash(self) -> None:
        import json

        from reveille.adapters.renderer import _build_contributor_timeline_chart
        from reveille.domain.models import Commit, ContributorStats, RankedContributor

        ranked = [
            RankedContributor(
                stats=ContributorStats(
                    name=f"Dev {i}",
                    email=f"d{i}@example.com",
                    commit_count=5,
                    lines_added=1,
                    lines_deleted=0,
                    active_days=1,
                    first_commit_date=datetime.date(2026, 1, 1),
                    last_commit_date=datetime.date(2026, 2, 1),
                ),
                composite_score=1.0,
                percentile=50.0,
                tier=1,
                tier_designation="Private",
            )
            for i in range(3)
        ]
        commits = [
            Commit(
                sha=f"{index:040d}",
                author_name=r.stats.name,
                author_email=r.stats.email,
                timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
                + datetime.timedelta(days=index * 7),
                lines_added=1,
                lines_deleted=0,
            )
            for index, r in enumerate(ranked)
        ]
        traces = json.loads(_build_contributor_timeline_chart(commits, ranked))["data"]
        dashes = [t["line"]["dash"] for t in traces]
        assert len(set(dashes)) == len(dashes), (
            f"series share a dash pattern, so only colour separates them: {dashes}"
        )
