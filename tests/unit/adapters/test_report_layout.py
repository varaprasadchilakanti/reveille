# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Layout rules the report needs in order to be read at all.

Each was found by rendering the installed tool's output in a browser, at
desktop width, at phone width and printed to PDF, and each broke the page
for a reader rather than merely looking untidy. There is no browser in the
test suite, so these assert the CSS rule that fixes each one; every test was
seen to fail with its rule removed.
"""

from __future__ import annotations

import datetime
import re

import pytest

from reveille.adapters.renderer import Renderer
from reveille.domain.models import Commit
from tests.unit.adapters.test_lorenz_chart import _report_data


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> str:
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
    out = tmp_path_factory.mktemp("layout") / "report.html"
    Renderer().render(data, out)
    return out.read_text(encoding="utf-8")


def _declarations(rendered: str, selector: str) -> str:
    """Every declaration block whose selector list names `selector`."""
    # The report's own stylesheet only: the embedded Plotly bundle is several
    # megabytes of minified code that a CSS-shaped regex would crawl through.
    own = re.search(r"<style>(.*?)</style>", rendered, flags=re.DOTALL)
    assert own, "the report has no stylesheet"
    css = re.sub(r"/\*.*?\*/", "", own.group(1), flags=re.DOTALL)
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    found = [
        body for selectors, body in blocks if selector in [s.strip() for s in selectors.split(",")]
    ]
    assert found, f"no CSS rule for {selector}"
    return " ".join(" ".join(found).split())


@pytest.mark.unit
class TestTheContributorTable:
    """One long name must not push every figure off the screen."""

    @pytest.mark.parametrize("selector", [".contributor-name", ".contributor-email"])
    def test_an_unbroken_identity_can_wrap(self, rendered: str, selector: str) -> None:
        """A 257-character name with no spaces widened its column past the
        viewport, and every number column went with it.

        `overflow-wrap: anywhere`, not `break-word`: only `anywhere` lowers
        the cell's minimum width, which is what table layout reads.
        """
        assert "overflow-wrap: anywhere" in _declarations(rendered, selector)

    def test_the_last_row_has_no_stray_border(self, rendered: str) -> None:
        """The row header kept its bottom border on the last row, drawing a
        line under the first column only."""
        rule = _declarations(rendered, ".ranking-table tbody tr:last-child th")
        assert "border-bottom: none" in rule


@pytest.mark.unit
def test_no_hidden_table_widens_the_page(rendered: str) -> None:
    """`width: 1px` cannot shrink a table below its content, so a table
    carrying `.visually-hidden` kept its full width while clipped from
    sight. On a 375 px phone the page scrolled sideways to 468 px. The
    class belongs on a wrapping block, which does shrink."""
    assert not re.search(r"<table[^>]*class=\"[^\"]*visually-hidden", rendered)
    assert '<div class="visually-hidden"><table>' in rendered, "positive control"


#: Plotly's toolbar is about 26 px tall and sits at the top of the figure.
_TOOLBAR_CLEARANCE = 36


@pytest.mark.unit
class TestTheChartToolbarCoversNothing:
    """It covered the Lorenz legend, the median label and the top hotspot bar.

    Zoom and pan stay: the README promises them, and the toolbar is the only
    visible way back after a drag. On a device without hover Plotly shows it
    permanently, so there it is hidden, and on a desktop each chart keeps a
    top margin the toolbar fits into.
    """

    def test_hidden_where_nothing_can_hover(self, rendered: str) -> None:
        own = re.search(r"<style>(.*?)</style>", rendered, flags=re.DOTALL)
        assert own
        css = " ".join(own.group(1).split())
        match = re.search(r"@media \(hover: none\) \{(.*?\})\s*\}", css)
        assert match, "no rule for devices without hover"
        assert ".modebar-container" in match.group(1)
        assert "display: none" in match.group(1)

    def test_every_chart_leaves_room_above_the_plot(self) -> None:
        from reveille.adapters.renderer import _base_layout

        assert _base_layout()["margin"]["t"] >= _TOOLBAR_CLEARANCE

    def test_the_heatmap_too(self) -> None:
        from tests.unit.adapters.test_heatmap_window import _TEMPLATE

        source = _TEMPLATE.read_text(encoding="utf-8")
        heatmap = source[source.index("function renderHeatmap(") :]
        top = re.search(r"margin:\s*\{[^}]*\bt:\s*(\d+)", heatmap)
        assert top and int(top.group(1)) >= _TOOLBAR_CLEARANCE


def _print_rules(rendered: str) -> str:
    """The body of the stylesheet's `@media print` block, comments removed."""
    own = re.search(r"<style>(.*?)</style>", rendered, flags=re.DOTALL)
    assert own
    css = re.sub(r"/\*.*?\*/", "", own.group(1), flags=re.DOTALL)
    start = css.index("@media print {") + len("@media print {")
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[end], 0)
        end += 1
    return " ".join(css[start : end - 1].split())


def _print_rule(rendered: str, selector: str) -> str:
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", _print_rules(rendered))
    found = [body for sel, body in rules if selector in [s.strip() for s in sel.split(",")]]
    assert found, f"no print rule for {selector}"
    return " ".join(found)


@pytest.mark.unit
class TestPrintingToPdf:
    """Printed, the report lost the table's last columns, clipped every chart
    at the right edge, and started each section on a new page -- nine pages,
    the last holding only the footer."""

    def test_the_table_is_not_clipped(self, rendered: str) -> None:
        assert "overflow: visible !important" in _print_rule(rendered, ".table-wrapper")

    def test_sections_may_break_across_pages(self, rendered: str) -> None:
        avoided = re.findall(r"([^{}]+)\{[^{}]*break-inside: avoid", _print_rules(rendered))
        selectors = {s.strip() for group in avoided for s in group.split(",")}
        assert ".section" not in selectors
        assert ".chart-container" in selectors, "a chart is still kept whole"

    def test_a_heading_stays_with_its_section(self, rendered: str) -> None:
        assert "break-after: avoid" in _print_rule(rendered, ".section-title")

    def test_the_heatmap_fits_the_page(self, rendered: str) -> None:
        assert "overflow: visible" in _print_rule(rendered, ".heatmap-scroll")
        assert "min-width: 0" in _print_rule(rendered, "#chart-heatmap")

    def test_charts_are_redrawn_at_the_printed_width(self, rendered: str) -> None:
        """Printing reflows the page without a resize event, so a chart keeps
        the width it had on screen unless it is told. `beforeprint` fires
        before the print styles apply, and `Plotly.Plots.resize` redraws on a
        timer after the page is printed; both were tried and printed clipped
        charts. The print media query's change event is the moment the
        containers have their printed width."""
        assert "matchMedia('print')" in rendered
        handler = rendered[rendered.index("function fitChartsTo(") :]
        handler = handler[: handler.index("\n    }\n")]
        assert "initChart(id, theme)" in handler, "redrawn through the first-paint path"
        assert "renderHeatmap(" in handler
        for builder in ("function initChart(", "function renderHeatmap("):
            body = rendered[rendered.index(builder) :]
            body = body[: body.index("\n    }\n")]
            assert "if (printing) layout.width = divEl.clientWidth;" in body, builder

    def test_charts_print_in_the_light_theme(self, rendered: str) -> None:
        """The page prints light whatever theme it is in; the charts kept the
        reader's dark theme, and printed as dark panels on white paper."""
        handler = rendered[rendered.index("function fitChartsTo(") :]
        handler = handler[: handler.index("\n    }\n")]
        assert "var theme = printing ? 'light' : readTheme();" in handler


@pytest.mark.unit
def test_the_longest_hotspot_keeps_its_label() -> None:
    """Its value label sits past the bar's end and was clipped to the plot
    area at a printed page's width: "3,59" for 3,591."""
    import json

    from reveille.adapters.renderer import _build_hotspot_chart
    from reveille.domain.models import FileStats

    files = [
        FileStats(path=f"f{i}.py", commits=1, lines_added=i * 700, lines_deleted=0)
        for i in range(1, 6)
    ]
    figure = json.loads(_build_hotspot_chart(files))

    assert figure["data"][0]["cliponaxis"] is False
    assert figure["layout"]["margin"]["r"] >= 50
