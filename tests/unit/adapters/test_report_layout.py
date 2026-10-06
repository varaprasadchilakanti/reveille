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
