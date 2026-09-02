"""Unit tests for the Lorenz curve chart.

The Lorenz curve is what the default report shows *instead of* the contributor
ranking from 0.8.0 onwards. It was shipped with no test of any kind: the chart
could be deleted from the report entirely, its fill could cover the wrong
region, its Gini figure could be doubled, and the whole suite still passed.
The ranking it replaces has thirty-odd tests. That asymmetry is the wrong way
round, and these close it.

`domain/concentration.py` is tested separately and thoroughly; what is checked
here is the adapter that turns those numbers into a figure -- that the trace
exists, that the geometry says what the caption claims, and that the colours
stay coupled to the palette.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from reveille.adapters.renderer import (
    _CATEGORICAL_PALETTE,
    _EQUALITY_LINE_COLOUR,
    _build_lorenz_chart,
    _translucent,
)
from reveille.domain.concentration import gini_coefficient
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"

_PROVENANCE = AnalysisProvenance(
    reveille_version="0.0.0-test",
    schema_version=SCHEMA_VERSION,
    head_sha="0" * 40,
    requested_branch=None,
    requested_since=None,
    requested_until=None,
    exclude_authors_count=0,
    min_commits=1,
    ranking_enabled=False,
    ranking_weights=None,
    mailmap_applied=False,
    deterministic=False,
)


def _report_data(counts: list[int]) -> ReportData:
    """A minimal report whose only interesting content is the distribution."""
    return ReportData(
        metadata=RepositoryMetadata(
            name="test-repo",
            remote_url=None,
            analysed_branch="main",
            total_commits=sum(counts),
            unique_contributors=len(counts),
            analysis_since=datetime.date(2024, 1, 1),
            analysis_until=datetime.date(2024, 6, 1),
            generated_at=datetime.datetime(2024, 6, 2, 12, 0, tzinfo=datetime.UTC),
        ),
        provenance=_PROVENANCE,
        ranked_contributors=_ranked(counts),
        commits=[],
    )


def _ranked(counts: list[int]) -> list[RankedContributor]:
    """Ranked contributors with the given commit counts. Only counts are used."""
    return [
        RankedContributor(
            stats=ContributorStats(
                name=f"Dev {i}",
                email=f"dev{i}@example.com",
                commit_count=c,
                lines_added=10,
                lines_deleted=1,
                active_days=5,
                first_commit_date=datetime.date(2024, 1, 1),
                last_commit_date=datetime.date(2024, 6, 1),
            ),
            composite_score=float(c),
            percentile=50.0,
            tier=1,
            tier_designation="Private",
        )
        for i, c in enumerate(counts)
    ]


def _figure(counts: list[int]) -> dict:
    """The chart as a parsed Plotly figure."""
    return json.loads(_build_lorenz_chart(_ranked(counts)))


@pytest.mark.unit
class TestLorenzChartIsPresent:
    """Deleting the chart must fail a test. Previously it did not."""

    def test_chart_is_built_for_two_or_more_contributors(self) -> None:
        assert _build_lorenz_chart(_ranked([5, 3])) != "null"

    def test_figure_has_both_traces(self) -> None:
        """The equality reference and the observed curve. Neither is optional."""
        assert len(_figure([10, 5, 1])["data"]) == 2

    def test_axes_and_title_are_labelled(self) -> None:
        layout = _figure([10, 5, 1])["layout"]
        assert "contributors" in layout["xaxis"]["title"]["text"].lower()
        assert "commits" in layout["yaxis"]["title"]["text"].lower()
        assert "Gini coefficient" in layout["title"]["text"]


@pytest.mark.unit
class TestLorenzChartDegenerateCases:
    """A curve over one person is the diagonal, which states nothing."""

    def test_single_contributor_yields_null(self) -> None:
        assert _build_lorenz_chart(_ranked([7])) == "null"

    def test_empty_yields_null(self) -> None:
        assert _build_lorenz_chart([]) == "null"


@pytest.mark.unit
class TestLorenzChartGeometry:
    """The plotted shape must agree with what the caption and title assert."""

    def test_equality_line_is_the_diagonal(self) -> None:
        equality = _figure([10, 5, 1])["data"][0]
        assert list(equality["x"]) == [0, 100]
        assert list(equality["y"]) == [0, 100]

    def test_curve_spans_zero_to_one_hundred_percent(self) -> None:
        curve = _figure([10, 5, 1])["data"][1]
        assert curve["x"][0] == 0 and curve["y"][0] == 0
        assert curve["x"][-1] == 100 and curve["y"][-1] == 100

    def test_curve_never_rises_above_the_equality_line(self) -> None:
        """A Lorenz curve bows *below* the diagonal, by definition."""
        curve = _figure([50, 20, 20, 5, 5])["data"][1]
        assert all(y <= x + 1e-6 for x, y in zip(curve["x"], curve["y"], strict=True))

    def test_curve_is_the_diagonal_when_everyone_is_equal(self) -> None:
        curve = _figure([4, 4, 4, 4])["data"][1]
        assert all(abs(y - x) < 1e-6 for x, y in zip(curve["x"], curve["y"], strict=True))

    def test_fill_is_between_the_curve_and_the_equality_line(self) -> None:
        """`tozeroy` would shade the area under the curve -- the wrong region.

        The shaded band is the *gap* between observed and equal, which is the
        quantity the Gini coefficient measures.
        """
        assert _figure([10, 5, 1])["data"][1]["fill"] == "tonexty"

    def test_equality_trace_is_drawn_first(self) -> None:
        """`tonexty` fills to the preceding trace, so the order is load-bearing."""
        assert _figure([10, 5, 1])["data"][0]["name"] == "Perfect equality"


@pytest.mark.unit
class TestLorenzChartTitleReportsTheRealGini:
    """The title is the only number a reader takes away. It must not drift."""

    @pytest.mark.parametrize(
        "counts",
        [[10, 5, 1], [4, 4, 4, 4], [100, 1, 1, 1], [7, 3], [50, 20, 20, 5, 5]],
    )
    def test_title_matches_the_domain_calculation(self, counts: list[int]) -> None:
        title = _figure(counts)["layout"]["title"]["text"]
        assert title == f"Gini coefficient: {gini_coefficient(counts):.2f}"

    def test_equal_distribution_reports_zero(self) -> None:
        assert _figure([4, 4, 4, 4])["layout"]["title"]["text"] == "Gini coefficient: 0.00"


@pytest.mark.unit
class TestLorenzChartColours:
    """Colour here separates the reference line from the measurement."""

    def test_curve_uses_the_first_categorical_hue(self) -> None:
        assert _figure([10, 5, 1])["data"][1]["line"]["color"] == _CATEGORICAL_PALETTE[0]

    def test_equality_line_uses_the_neutral_not_a_contributor_hue(self) -> None:
        """The diagonal is a reference, not a series; a categorical hue would
        read as one more contributor."""
        colour = _figure([10, 5, 1])["data"][0]["line"]["color"]
        assert colour == _EQUALITY_LINE_COLOUR
        assert colour not in _CATEGORICAL_PALETTE

    def test_fill_is_derived_from_the_line_colour(self) -> None:
        """Guards the literal-rgba seam: a palette change must move both."""
        curve = _figure([10, 5, 1])["data"][1]
        assert curve["fillcolor"] == _translucent(_CATEGORICAL_PALETTE[0], 0.12)

    def test_equality_line_is_visually_distinguished_beyond_colour(self) -> None:
        """Dashed, so the two traces stay separable without colour vision."""
        assert _figure([10, 5, 1])["data"][0]["line"]["dash"] == "dot"


@pytest.mark.unit
class TestLorenzChartNamesNobody:
    """The reason this chart survives into the default report while the
    per-person ranking does not: it characterises the repository."""

    def test_no_contributor_name_or_email_appears_in_the_figure(self) -> None:
        payload = _build_lorenz_chart(_ranked([10, 5, 1]))
        assert "Dev 0" not in payload
        assert "@example.com" not in payload


@pytest.mark.unit
class TestLorenzChartReachesTheReport:
    """Testing the builder is not enough.

    Every geometry and colour test above passes with the chart disconnected
    from the report entirely -- verified by mutation. These assert the wiring:
    the spec is produced, embedded, and rendered.
    """

    def test_build_charts_emits_a_real_lorenz_spec(self) -> None:
        from reveille.adapters.renderer import Renderer

        data = _report_data([10, 5, 1])
        charts = Renderer()._build_charts(data)
        assert charts["lorenz"] != "null"
        assert json.loads(charts["lorenz"])["data"]

    def test_template_embeds_and_renders_the_spec(self) -> None:
        """The id the client script reads, and the container it draws into."""
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert 'id="spec-lorenz"' in template
        assert "charts.lorenz" in template
        assert 'id="chart-lorenz"' in template

    def test_rendered_report_contains_the_curve(self, tmp_path) -> None:
        from reveille.adapters.renderer import Renderer

        out = tmp_path / "r.html"
        Renderer().render(_report_data([10, 5, 1]), out)
        html = out.read_text(encoding="utf-8")
        assert 'id="spec-lorenz"' in html
        assert "Gini coefficient" in html
        assert "Perfect equality" in html
