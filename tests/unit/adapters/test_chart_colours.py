"""Unit tests for chart colour assignment.

Colour in these charts encodes *identity* -- which line, slice, or bar belongs
to which contributor. That makes a repeated colour a false statement rather
than an aesthetic lapse: two contributors drawn identically cannot be told
apart, and the legend stops being a key.

Two defects of exactly that kind were found in v0.7.0's renderer and are
guarded here. The contributor timeline drew one trace per contributor with
`palette[i % len(palette)]`, so the ninth contributor silently reused the
first one's colour. And the commit-share pie aggregated past eight slices but
then asked for nine colours from an eight-colour palette, so "Other
Contributors" wrapped around and shared a colour with the top-ranked
contributor inside the same chart.

The palette itself is a measured set rather than a chosen one -- see the
comment on `_CATEGORICAL_PALETTE` for the perceptual-distance thresholds it
was validated against.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from reveille.adapters.renderer import (
    _CATEGORICAL_PALETTE,
    _MAX_CHART_HEIGHT,
    _MAX_SERIES,
    _OTHER_LABEL,
    _OTHER_SLICE_COLOUR,
    _PIE_MAX_SLICES,
    _build_commit_share_pie,
    _build_contributor_commits_chart,
    _build_contributor_timeline_chart,
    _pie_colors,
)
from reveille.domain.models import Commit, ContributorStats, RankedContributor

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


def _ranked(n: int) -> list[RankedContributor]:
    """Build n ranked contributors with descending commit counts."""
    return [
        RankedContributor(
            stats=ContributorStats(
                name=f"Dev {i}",
                email=f"dev{i}@example.com",
                commit_count=100 - i,
                lines_added=10,
                lines_deleted=1,
                active_days=5,
                first_commit_date=datetime.date(2024, 1, 1),
                last_commit_date=datetime.date(2024, 6, 1),
            ),
            composite_score=float(100 - i),
            percentile=50.0,
            tier=1,
            tier_designation="Private",
        )
        for i in range(n)
    ]


def _commits(n_contributors: int) -> list[Commit]:
    """One commit per contributor per week, so every series has data."""
    return [
        Commit(
            sha=f"{i}{w}",
            author_name=f"Dev {i}",
            author_email=f"dev{i}@example.com",
            timestamp=datetime.datetime(2024, 1, 1) + datetime.timedelta(weeks=w),
            lines_added=1,
            lines_deleted=0,
        )
        for i in range(n_contributors)
        for w in range(3)
    ]


@pytest.mark.unit
class TestPalette:
    """The palette itself must be internally sound before anything uses it."""

    def test_no_colour_appears_twice(self) -> None:
        """A repeated hue in the source list would defeat every other guard."""
        assert len(set(_CATEGORICAL_PALETTE)) == len(_CATEGORICAL_PALETTE)

    def test_series_cap_matches_the_palette_length(self) -> None:
        """The cap exists so the palette is never asked to wrap."""
        assert len(_CATEGORICAL_PALETTE) == _MAX_SERIES

    def test_pie_slice_cap_does_not_exceed_the_palette(self) -> None:
        """Named slices must all be able to take a distinct hue."""
        assert len(_CATEGORICAL_PALETTE) >= _PIE_MAX_SLICES

    def test_residual_colour_is_not_a_palette_hue(self) -> None:
        """ "Other" is a residual, not an identity, so it must look different."""
        assert _OTHER_SLICE_COLOUR not in _CATEGORICAL_PALETTE


@pytest.mark.unit
class TestPieColours:
    """`_pie_colors` must never hand back a duplicate."""

    def test_named_slices_take_the_palette_in_order(self) -> None:
        """Colour follows the entity's rank position, deterministically."""
        assert _pie_colors(4) == _CATEGORICAL_PALETTE[:4]

    def test_residual_slice_takes_the_neutral(self) -> None:
        """With an aggregate present the last slice is the reserved neutral."""
        colours = _pie_colors(_PIE_MAX_SLICES + 1, has_other=True)

        assert colours[-1] == _OTHER_SLICE_COLOUR
        assert colours[:-1] == _CATEGORICAL_PALETTE[:_PIE_MAX_SLICES]

    def test_a_full_pie_with_a_residual_has_no_repeated_colour(self) -> None:
        """This is the exact v0.7.0 defect: nine slices, eight colours."""
        colours = _pie_colors(_PIE_MAX_SLICES + 1, has_other=True)

        assert len(set(colours)) == len(colours)


@pytest.mark.unit
class TestRenderedChartsNeverRepeatAColour:
    """The guarantee must hold in the emitted Plotly spec, not just the helper."""

    def test_commit_share_pie_with_more_contributors_than_slices(self) -> None:
        """Rendered end to end, because the helper is only half the path."""
        spec = json.loads(_build_commit_share_pie(_ranked(_PIE_MAX_SLICES + 5)))
        trace = spec["data"][0]
        colours = trace["marker"]["colors"]

        assert trace["labels"][-1] == _OTHER_LABEL
        assert len(colours) == len(trace["labels"])
        assert len(set(colours)) == len(colours)

    def test_contributor_timeline_caps_series_at_the_palette_length(self) -> None:
        """Beyond the cap the palette would have to repeat, so it stops."""
        spec = json.loads(_build_contributor_timeline_chart(_commits(20), _ranked(20)))

        assert len(spec["data"]) == _MAX_SERIES

    def test_contributor_timeline_never_repeats_a_line_colour(self) -> None:
        """Two contributors sharing a colour and a style are indistinguishable."""
        spec = json.loads(_build_contributor_timeline_chart(_commits(20), _ranked(20)))
        colours = [t["line"]["color"] for t in spec["data"]]

        assert len(set(colours)) == len(colours)


@pytest.mark.unit
class TestHeatmapRamps:
    """The heatmap ramp is theme-specific and lives in the template."""

    def test_both_theme_ramps_are_defined(self) -> None:
        """A single ramp cannot encode magnitude on two different surfaces.

        The previous fixed ramp ended at a near-black blue: 9.73:1 against the
        light plot background but 1.67:1 against the dark one, so in dark mode
        the busiest days faded out while the quietest glowed. The chart read
        backwards precisely where the data mattered most.
        """
        template = _TEMPLATE.read_text(encoding="utf-8")

        assert "HEATMAP_SCALES" in template
        assert "light:" in template
        assert "dark:" in template

    def test_theme_toggle_rerenders_rather_than_relayouts_the_heatmap(self) -> None:
        """A colorscale lives on the trace, which `Plotly.relayout` ignores.

        Swapping only the layout would leave a ramp built for the other
        surface, reintroducing the inverted reading this pair exists to fix.
        """
        template = _TEMPLATE.read_text(encoding="utf-8")
        start = template.index("function applyThemeToCharts")
        body = template[start : template.index("function toggleTheme")]

        assert "renderHeatmap(" in body


@pytest.mark.unit
class TestChartHeightIsBounded:
    """A chart taller than any browser will render is an unusable artefact."""

    def test_height_is_capped_for_a_large_contributor_count(self) -> None:
        """5,000 contributors produced a chart 220,080 pixels tall."""
        spec = json.loads(_build_contributor_commits_chart(_ranked(5000)))

        assert spec["layout"]["height"] <= _MAX_CHART_HEIGHT

    def test_height_still_grows_for_ordinary_repositories(self) -> None:
        """The cap must not flatten every chart to one size."""
        small = json.loads(_build_contributor_commits_chart(_ranked(3)))
        larger = json.loads(_build_contributor_commits_chart(_ranked(12)))

        assert small["layout"]["height"] < larger["layout"]["height"] <= _MAX_CHART_HEIGHT
