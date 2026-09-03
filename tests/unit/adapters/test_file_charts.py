# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The two file-level charts, and the reader that feeds them.

`git log --numstat` was already carrying a path on every line and the
totals were being summed out of a structure that had them. These charts
therefore cost no extra Git work -- only the parsing already paid for --
which is the reason they can exist without touching the read that 0.7.0
made 9.4x faster.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reveille.adapters.git_reader import _iter_numstat, _rename_destination
from reveille.adapters.renderer import _build_extension_chart, _build_hotspot_chart
from reveille.domain.models import FileStats

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


def _file(path: str, commits: int = 1, added: int = 0, deleted: int = 0) -> FileStats:
    return FileStats(path=path, commits=commits, lines_added=added, lines_deleted=deleted)


@pytest.mark.unit
class TestNumstatParsing:
    """The paths were being discarded, not absent."""

    def test_a_plain_line_yields_path_and_counts(self) -> None:
        assert list(_iter_numstat("10\t2\tsrc/a.py")) == [("src/a.py", 10, 2)]

    def test_a_binary_file_contributes_zero(self) -> None:
        assert list(_iter_numstat("-\t-\tlogo.png")) == [("logo.png", 0, 0)]

    def test_a_short_line_is_skipped(self) -> None:
        assert list(_iter_numstat("garbage")) == []

    def test_an_empty_block_yields_nothing(self) -> None:
        assert list(_iter_numstat("")) == []

    def test_a_path_containing_spaces_survives(self) -> None:
        assert list(_iter_numstat("1\t0\tdocs/my file.md")) == [("docs/my file.md", 1, 0)]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("a.py", "a.py"),
            ("old.py => new.py", "new.py"),
            ("src/{old => new}/f.py", "src/new/f.py"),
            ("src/a/{x.py => y.py}", "src/a/y.py"),
        ],
    )
    def test_a_rename_resolves_to_its_destination(self, raw: str, expected: str) -> None:
        """Counting both sides doubles a file; counting the source attributes
        churn to a path that no longer exists."""
        assert _rename_destination(raw) == expected


@pytest.mark.unit
class TestTheHotspotChart:
    def test_empty_input_produces_no_chart(self) -> None:
        assert _build_hotspot_chart([]) == "null"

    def test_only_generated_files_produces_no_chart(self) -> None:
        """Excluding every candidate must not draw an empty axis."""
        assert _build_hotspot_chart([_file("poetry.lock", added=999)]) == "null"

    def test_the_highest_churn_is_drawn_last_so_it_reads_at_the_top(self) -> None:
        files = [_file("small.py", added=1), _file("big.py", added=900)]
        trace = json.loads(_build_hotspot_chart(files))["data"][0]
        assert trace["y"][-1] == "big.py"

    def test_the_hover_reports_commits_as_well_as_churn(self) -> None:
        trace = json.loads(_build_hotspot_chart([_file("a.py", commits=7, added=9)]))["data"][0]
        assert trace["customdata"] == [7]
        assert "Commits" in trace["hovertemplate"]

    def test_no_contributor_is_named(self) -> None:
        emitted = _build_hotspot_chart([_file("a.py", added=10)])
        assert "@" not in emitted


@pytest.mark.unit
class TestTheExtensionChart:
    def test_empty_input_produces_no_chart(self) -> None:
        assert _build_extension_chart([]) == "null"

    def test_totals_are_preserved(self) -> None:
        files = [_file(f"f{i}.e{i}", added=10) for i in range(20)]
        trace = json.loads(_build_extension_chart(files))["data"][0]
        assert sum(trace["y"]) == 200

    def test_it_uses_a_palette_colour_rather_than_a_literal(self) -> None:
        from reveille.adapters.renderer import _CATEGORICAL_PALETTE

        trace = json.loads(_build_extension_chart([_file("a.py", added=1)]))["data"][0]
        assert trace["marker"]["color"] in _CATEGORICAL_PALETTE


@pytest.mark.unit
class TestBothAreWiredIntoTheReport:
    """A builder nothing renders is dead code."""

    @pytest.mark.parametrize("chart", ["hotspots", "extensions"])
    def test_the_template_embeds_and_draws_it(self, chart: str) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert f'id="spec-{chart}"' in template
        assert f"charts.{chart} | safe" in template, (
            "without `| safe` the specification is HTML-escaped and never parses"
        )
        assert f'id="chart-{chart}"' in template
        assert f"'{chart}'" in template, "the client script never initialises it"

    def test_the_reader_exposes_file_stats(self) -> None:
        """The service reads this attribute; it must exist before any call."""
        from reveille.adapters.git_reader import GitReader

        reader = GitReader(Path(__file__).resolve().parents[3])
        assert reader.file_stats == ()

    def test_report_data_carries_them(self) -> None:
        from reveille.domain.models import ReportData

        assert "file_stats" in ReportData.__dataclass_fields__


@pytest.mark.unit
class TestTheRepositoryProfileChart:
    """A radar has known weaknesses; these assert they are handled."""

    def test_the_polygon_is_closed(self) -> None:
        from reveille.adapters.renderer import _build_profile_chart
        from reveille.domain.profile import AXIS_ORDER, ProfileAxis

        # Distinct values per axis: with every axis equal, a closure
        # assertion is true whether or not the loop was closed.
        axes = [ProfileAxis(name, 0.2 + index * 0.15, "d") for index, name in enumerate(AXIS_ORDER)]
        trace = json.loads(_build_profile_chart(axes))["data"][0]
        assert len(trace["r"]) == len(trace["theta"]) == len(AXIS_ORDER) + 1, (
            "an unclosed radar leaves a gap between the last axis and the first"
        )
        assert trace["theta"][0] == trace["theta"][-1]
        assert trace["r"][0] == trace["r"][-1]

    def test_every_vertex_is_labelled_with_its_value(self) -> None:
        """The figure must be readable as numbers, not only as a shape."""
        from reveille.adapters.renderer import _build_profile_chart
        from reveille.domain.profile import AXIS_ORDER, ProfileAxis

        axes = [ProfileAxis(name, 0.42, "d") for name in AXIS_ORDER]
        trace = json.loads(_build_profile_chart(axes))["data"][0]
        assert "text" in trace["mode"]
        assert set(trace["text"]) == {"42%"}

    def test_the_radial_axis_is_a_true_zero_to_one(self) -> None:
        """No rescaling: a 40% axis must sit at 40% of the radius."""
        from reveille.adapters.renderer import _build_profile_chart
        from reveille.domain.profile import AXIS_ORDER, ProfileAxis

        axes = [ProfileAxis(name, 0.4, "d") for name in AXIS_ORDER]
        layout = json.loads(_build_profile_chart(axes))["layout"]
        assert layout["polar"]["radialaxis"]["range"] == [0, 1]

    def test_no_profile_produces_no_chart(self) -> None:
        from reveille.adapters.renderer import _build_profile_chart

        assert _build_profile_chart([]) == "null"

    def test_it_is_wired_into_the_report(self) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert 'id="spec-profile"' in template
        assert "charts.profile | safe" in template
        assert 'id="chart-profile"' in template
        assert "'profile'" in template

    def test_the_caveat_about_area_is_stated_in_the_report(self) -> None:
        """A radar that does not warn about its own form misleads."""
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert "order of the axes" in template
        assert "Cleveland" in template


@pytest.mark.unit
class TestTheContributionBreakdownUsesOneFormPerQuestion:
    """Part-of-whole gets the pie; two series get the bar."""

    def test_the_share_pie_is_wired_and_the_duplicates_are_not(self) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert 'id="chart-pie_commits"' in template, (
            "commit share is part-of-whole, which is what a pie is for"
        )
        assert 'id="chart-contributor_lines"' in template, (
            "added against deleted is two series, which a pie cannot show"
        )
        for gone in ("chart-contributor_commits", "chart-pie_lines"):
            assert gone not in template, f"{gone} duplicated the chart beside it"

    def test_no_builder_is_left_unwired(self) -> None:
        """A builder nothing renders is dead code."""
        import inspect

        from reveille.adapters import renderer as module

        source = inspect.getsource(module.Renderer._build_charts)
        for name, function in vars(module).items():
            if not (name.startswith("_build_") and inspect.isfunction(function)):
                continue
            if name == "_build_heatmap_data":
                continue  # consumed by the client script, not a chart spec
            assert name in source, f"{name} is never called by _build_charts"
