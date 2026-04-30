"""Unit tests for reveille.adapters.renderer module-level functions.

The Renderer class itself is covered by the e2e test suite.
These tests exercise chart construction, derived metric helpers,
and serialisation utilities directly. All chart builders now return
Plotly JSON specification strings (or the sentinel string 'null')
rather than HTML fragments. Tests verify JSON validity, structural
completeness, and the behavioural contract for edge cases.
"""

from __future__ import annotations

import datetime
import json

import plotly.graph_objects as go
import pytest

from reveille.adapters.renderer import (
    _aggregate_pie_data,
    _build_commit_share_pie,
    _build_contributor_commits_chart,
    _build_contributor_lines_chart,
    _build_heatmap_chart,
    _build_heatmap_monthly,
    _build_heatmap_weekly,
    _build_heatmap_yearly,
    _build_lines_share_pie,
    _build_timeline_chart,
    _compute_bus_factor,
    _compute_longest_inactive_streak,
    _to_json,
)
from reveille.domain.models import Commit, ContributorStats, RankedContributor

# ------------------------------------------------------------------
# Shared factory helpers
# ------------------------------------------------------------------


def _make_commit(
    date: datetime.date,
    email: str = "a@example.com",
    lines_added: int = 10,
    lines_deleted: int = 2,
) -> Commit:
    return Commit(
        sha=f"{email[:3]}{date.isoformat()}",
        author_name="Author",
        author_email=email,
        timestamp=datetime.datetime(
            date.year,
            date.month,
            date.day,
            12,
            0,
            tzinfo=datetime.UTC,
        ),
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )


def _make_ranked(
    name: str,
    commit_count: int,
    lines_added: int = 200,
    lines_deleted: int = 50,
    tier: int = 4,
    designation: str = "Senior Specialist",
) -> RankedContributor:
    stats = ContributorStats(
        name=name,
        email=f"{name.lower()}@example.com",
        commit_count=commit_count,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        active_days=max(1, commit_count // 2),
        first_commit_date=datetime.date(2024, 1, 1),
        last_commit_date=datetime.date(2024, 3, 31),
    )
    return RankedContributor(
        stats=stats,
        composite_score=0.5,
        percentile=50.0,
        tier=tier,
        tier_designation=designation,
    )


def _is_valid_chart_json(value: str) -> bool:
    """Return True if value is a non-null JSON string with 'data' and 'layout' keys."""
    if value == "null":
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return "data" in parsed and "layout" in parsed


# ------------------------------------------------------------------
# _compute_bus_factor
# ------------------------------------------------------------------


@pytest.mark.unit
class TestComputeBusFactor:
    """Tests for the bus factor derived metric helper."""

    def test_empty_ranked_returns_zero(self) -> None:
        assert _compute_bus_factor([]) == 0

    def test_single_contributor_returns_one(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=20)]
        assert _compute_bus_factor(ranked) == 1

    def test_two_equal_contributors_returns_one(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=10),
            _make_ranked("Bob", commit_count=10),
        ]
        assert _compute_bus_factor(ranked) == 1

    def test_skewed_distribution_returns_one(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=90),
            _make_ranked("Bob", commit_count=5),
            _make_ranked("Carol", commit_count=5),
        ]
        assert _compute_bus_factor(ranked) == 1

    def test_even_distribution_across_four_returns_two(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=25),
            _make_ranked("Bob", commit_count=25),
            _make_ranked("Carol", commit_count=25),
            _make_ranked("Dan", commit_count=25),
        ]
        assert _compute_bus_factor(ranked) == 2

    def test_zero_total_commits_returns_zero(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=0)]
        assert _compute_bus_factor(ranked) == 0


# ------------------------------------------------------------------
# _compute_longest_inactive_streak
# ------------------------------------------------------------------


@pytest.mark.unit
class TestComputeLongestInactiveStreak:
    """Tests for the inactive streak derived metric helper."""

    def test_no_commits_returns_full_window_length(self) -> None:
        streak = _compute_longest_inactive_streak(
            commits=[],
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 10),
        )
        assert streak == 9

    def test_commits_every_day_returns_zero(self) -> None:
        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 1, 5)
        commits = [_make_commit(start + datetime.timedelta(days=i)) for i in range(5)]
        assert (
            _compute_longest_inactive_streak(
                commits=commits, window_start=start, window_end=end
            )
            == 0
        )

    def test_gap_in_the_middle_is_detected(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 1)),
            _make_commit(datetime.date(2024, 1, 8)),
        ]
        streak = _compute_longest_inactive_streak(
            commits=commits,
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 10),
        )
        assert streak == 6

    def test_gap_at_start_of_window_is_detected(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 5))]
        streak = _compute_longest_inactive_streak(
            commits=commits,
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 5),
        )
        assert streak == 4


# ------------------------------------------------------------------
# _build_timeline_chart
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildTimelineChart:
    """Tests for the weekly commit timeline chart builder."""

    def test_empty_commits_returns_null_sentinel(self) -> None:
        assert _build_timeline_chart([]) == "null"

    def test_with_commits_returns_valid_chart_json(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 15)),
            _make_commit(datetime.date(2024, 2, 5)),
        ]
        assert _is_valid_chart_json(_build_timeline_chart(commits))

    def test_aggregates_commits_within_same_week_without_error(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 9)),
        ]
        assert _is_valid_chart_json(_build_timeline_chart(commits))

    def test_layout_does_not_contain_bgcolor_keys(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 8))]
        parsed = json.loads(_build_timeline_chart(commits))
        layout = parsed.get("layout", {})
        assert "paper_bgcolor" not in layout
        assert "plot_bgcolor" not in layout


# ------------------------------------------------------------------
# _build_heatmap_chart — dispatch and granularity variants
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildHeatmapChart:
    """Tests for the heatmap chart builder and its granularity variants."""

    def test_empty_commits_returns_null_sentinel(self) -> None:
        assert _build_heatmap_chart([], "weekly") == "null"
        assert _build_heatmap_chart([], "monthly") == "null"
        assert _build_heatmap_chart([], "yearly") == "null"

    def test_weekly_returns_valid_chart_json(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 15)),
        ]
        assert _is_valid_chart_json(_build_heatmap_weekly(commits))

    def test_monthly_returns_valid_chart_json(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 2, 5)),
            _make_commit(datetime.date(2024, 3, 20)),
        ]
        assert _is_valid_chart_json(_build_heatmap_monthly(commits))

    def test_yearly_returns_valid_chart_json(self) -> None:
        commits = [
            _make_commit(datetime.date(2023, 6, 1)),
            _make_commit(datetime.date(2024, 3, 15)),
        ]
        assert _is_valid_chart_json(_build_heatmap_yearly(commits))

    def test_monthly_z_matrix_has_seven_rows(self) -> None:
        """Seven rows correspond to the seven days of the week."""
        commits = [_make_commit(datetime.date(2024, 1, d)) for d in (1, 8, 15, 22)]
        parsed = json.loads(_build_heatmap_monthly(commits))
        z = parsed["data"][0]["z"]
        assert len(z) == 7

    def test_yearly_z_matrix_has_twelve_rows(self) -> None:
        """Twelve rows correspond to the twelve months of the year."""
        commits = [_make_commit(datetime.date(2023, m, 1)) for m in range(1, 13)]
        parsed = json.loads(_build_heatmap_yearly(commits))
        z = parsed["data"][0]["z"]
        assert len(z) == 12

    def test_monthly_column_count_matches_distinct_months(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 5)),
            _make_commit(datetime.date(2024, 3, 10)),
        ]
        parsed = json.loads(_build_heatmap_monthly(commits))
        # Two distinct months: 2024-01 and 2024-03.
        x_labels = parsed["data"][0]["x"]
        assert len(x_labels) == 2

    def test_yearly_column_count_matches_distinct_years(self) -> None:
        commits = [
            _make_commit(datetime.date(2022, 6, 1)),
            _make_commit(datetime.date(2023, 6, 1)),
            _make_commit(datetime.date(2024, 6, 1)),
        ]
        parsed = json.loads(_build_heatmap_yearly(commits))
        x_labels = parsed["data"][0]["x"]
        assert len(x_labels) == 3

    def test_dispatch_weekly_via_build_heatmap_chart(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 8))]
        assert _is_valid_chart_json(_build_heatmap_chart(commits, "weekly"))

    def test_dispatch_monthly_via_build_heatmap_chart(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 8))]
        assert _is_valid_chart_json(_build_heatmap_chart(commits, "monthly"))

    def test_dispatch_yearly_via_build_heatmap_chart(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 8))]
        assert _is_valid_chart_json(_build_heatmap_chart(commits, "yearly"))


# ------------------------------------------------------------------
# _build_contributor_commits_chart
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContributorCommitsChart:
    """Tests for the horizontal commit count bar chart builder."""

    def test_empty_ranked_returns_null_sentinel(self) -> None:
        assert _build_contributor_commits_chart([]) == "null"

    def test_single_contributor_returns_valid_chart_json(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=15)]
        assert _is_valid_chart_json(_build_contributor_commits_chart(ranked))

    def test_multiple_contributors_return_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=30),
            _make_ranked("Bob", commit_count=12),
            _make_ranked("Carol", commit_count=5),
        ]
        assert _is_valid_chart_json(_build_contributor_commits_chart(ranked))


# ------------------------------------------------------------------
# _build_contributor_lines_chart
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContributorLinesChart:
    """Tests for the grouped lines changed bar chart builder."""

    def test_empty_ranked_returns_null_sentinel(self) -> None:
        assert _build_contributor_lines_chart([]) == "null"

    def test_single_contributor_returns_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=10, lines_added=500, lines_deleted=80)
        ]
        assert _is_valid_chart_json(_build_contributor_lines_chart(ranked))

    def test_multiple_contributors_return_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20, lines_added=1200, lines_deleted=300),
            _make_ranked("Bob", commit_count=8, lines_added=400, lines_deleted=100),
        ]
        assert _is_valid_chart_json(_build_contributor_lines_chart(ranked))

    def test_chart_contains_two_traces_for_added_and_deleted(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=10),
            _make_ranked("Bob", commit_count=5),
        ]
        parsed = json.loads(_build_contributor_lines_chart(ranked))
        assert len(parsed["data"]) == 2


# ------------------------------------------------------------------
# _build_commit_share_pie and _build_lines_share_pie
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildPieCharts:
    """Tests for the commit share and lines share donut charts."""

    def test_single_contributor_commits_returns_null_sentinel(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=10)]
        assert _build_commit_share_pie(ranked) == "null"

    def test_single_contributor_lines_returns_null_sentinel(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=10)]
        assert _build_lines_share_pie(ranked) == "null"

    def test_two_contributors_commits_returns_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20),
            _make_ranked("Bob", commit_count=10),
        ]
        assert _is_valid_chart_json(_build_commit_share_pie(ranked))

    def test_two_contributors_lines_returns_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20, lines_added=800, lines_deleted=100),
            _make_ranked("Bob", commit_count=5, lines_added=200, lines_deleted=40),
        ]
        assert _is_valid_chart_json(_build_lines_share_pie(ranked))

    def test_pie_trace_has_hole_property(self) -> None:
        """Confirms the donut form: hole must be present and non-zero."""
        ranked = [
            _make_ranked("Alice", commit_count=20),
            _make_ranked("Bob", commit_count=10),
        ]
        parsed = json.loads(_build_commit_share_pie(ranked))
        hole = parsed["data"][0].get("hole")
        assert hole is not None
        assert hole > 0


# ------------------------------------------------------------------
# _aggregate_pie_data
# ------------------------------------------------------------------


@pytest.mark.unit
class TestAggregatePieData:
    """Tests for the pie data aggregation helper."""

    def test_fewer_than_max_slices_returned_unchanged(self) -> None:
        items = [("Alice", 10), ("Bob", 8), ("Carol", 5)]
        labels, values = _aggregate_pie_data(items)
        assert labels == ["Alice", "Bob", "Carol"]
        assert values == [10, 8, 5]

    def test_exactly_max_slices_returned_unchanged(self) -> None:
        items = [(f"Contributor{i}", 10 - i) for i in range(8)]
        labels, _values = _aggregate_pie_data(items)
        assert len(labels) == 8
        assert "Other Contributors" not in labels

    def test_beyond_max_slices_aggregates_remainder(self) -> None:
        items = [(f"Contributor{i}", 10) for i in range(10)]
        labels, values = _aggregate_pie_data(items)
        assert len(labels) == 9  # 8 named + 1 aggregate
        assert labels[-1] == "Other Contributors"
        assert values[-1] == 20  # 2 contributors * 10 each

    def test_aggregate_value_is_sum_of_remainder(self) -> None:
        items = [
            ("A", 100),
            ("B", 80),
            ("C", 60),
            ("D", 40),
            ("E", 30),
            ("F", 20),
            ("G", 10),
            ("H", 5),
            ("I", 3),
            ("J", 2),
        ]
        labels, values = _aggregate_pie_data(items)
        # First 8 items kept; I (3) and J (2) aggregated = 5.
        assert values[-1] == 5
        assert labels[-1] == "Other Contributors"

    def test_output_lengths_are_equal(self) -> None:
        items = [(f"C{i}", i + 1) for i in range(15)]
        labels, values = _aggregate_pie_data(items)
        assert len(labels) == len(values)


# ------------------------------------------------------------------
# _to_json — security and type contract
# ------------------------------------------------------------------


@pytest.mark.unit
class TestToJson:
    """Tests for the Plotly figure JSON serialisation helper."""

    def _simple_figure(self) -> go.Figure:
        fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))
        return fig

    def test_returns_valid_json_string(self) -> None:
        result = _to_json(self._simple_figure())
        parsed = json.loads(result)
        assert "data" in parsed
        assert "layout" in parsed

    def test_paper_bgcolor_absent_from_output(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(paper_bgcolor="#ffffff")
        result = _to_json(fig)
        layout = json.loads(result)["layout"]
        assert "paper_bgcolor" not in layout

    def test_plot_bgcolor_absent_from_output(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(plot_bgcolor="#f0f0f0")
        result = _to_json(fig)
        layout = json.loads(result)["layout"]
        assert "plot_bgcolor" not in layout

    def test_font_color_absent_from_output(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(font={"color": "#000000", "size": 12})
        result = _to_json(fig)
        font = json.loads(result)["layout"].get("font", {})
        assert "color" not in font

    def test_font_size_preserved_after_color_removal(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(font={"color": "#000000", "size": 14})
        result = _to_json(fig)
        font = json.loads(result)["layout"].get("font", {})
        assert font.get("size") == 14

    def test_script_closing_tag_in_label_is_escaped(self) -> None:
        """A label containing </script> must not produce a raw closing tag."""
        fig = go.Figure(go.Bar(x=["</script>"], y=[1]))
        result = _to_json(fig)
        assert "</script>" not in result
        assert "<\\/script>" in result
