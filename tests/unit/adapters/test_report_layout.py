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
