"""Unit tests for reveille.adapters.renderer module-level functions.

The Renderer class itself is covered by integration tests on feat/cli.
These tests exercise the chart construction and derived metric helper
functions directly, as they are pure or near-pure functions whose
correctness can be verified without a running Jinja2 environment.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.adapters.renderer import (
    _build_contributor_commits_chart,
    _build_contributor_lines_chart,
    _build_heatmap_chart,
    _build_timeline_chart,
    _compute_bus_factor,
    _compute_longest_inactive_streak,
)
from reveille.domain.models import Commit, ContributorStats, RankedContributor

# ------------------------------------------------------------------
# Shared helpers
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
            date.year, date.month, date.day, 12, 0,
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
        # One contributor accounts for 50% of commits (10/20 = 50%).
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
        # Top contributor = 25%, top two = 50%. Bus factor is 2.
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
        commits = [
            _make_commit(start + datetime.timedelta(days=i))
            for i in range(5)
        ]
        streak = _compute_longest_inactive_streak(
            commits=commits,
            window_start=start,
            window_end=end,
        )
        assert streak == 0

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
        # Days 2-7 are inactive: 6 consecutive days.
        assert streak == 6

    def test_gap_at_start_of_window_is_detected(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 5))]
        streak = _compute_longest_inactive_streak(
            commits=commits,
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 5),
        )
        # Days 1-4 are inactive: 4 consecutive days.
        assert streak == 4


# ------------------------------------------------------------------
# Chart builders -- structural tests
# ------------------------------------------------------------------

@pytest.mark.unit
class TestBuildTimelineChart:
    """Tests for the weekly commit timeline chart builder."""

    def test_empty_commits_returns_placeholder(self) -> None:
        result = _build_timeline_chart([])
        assert "chart-empty" in result

    def test_with_commits_returns_non_empty_html(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 15)),
            _make_commit(datetime.date(2024, 2, 5)),
        ]
        result = _build_timeline_chart(commits)
        assert len(result) > 0
        assert "<div" in result

    def test_aggregates_commits_within_same_week(self) -> None:
        # Two commits in the same week should not raise any errors.
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 9)),
        ]
        result = _build_timeline_chart(commits)
        assert "<div" in result


@pytest.mark.unit
class TestBuildHeatmapChart:
    """Tests for the calendar heatmap chart builder."""

    def test_empty_commits_returns_placeholder(self) -> None:
        result = _build_heatmap_chart([])
        assert "chart-empty" in result

    def test_with_commits_returns_non_empty_html(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 15)),
        ]
        result = _build_heatmap_chart(commits)
        assert "<div" in result

    def test_multiple_days_of_week_handled(self) -> None:
        start = datetime.date(2024, 1, 7)
        commits = [
            _make_commit(start + datetime.timedelta(days=i))
            for i in range(7)
        ]
        result = _build_heatmap_chart(commits)
        assert "<div" in result


@pytest.mark.unit
class TestBuildContributorCommitsChart:
    """Tests for the horizontal commit count bar chart builder."""

    def test_empty_ranked_returns_placeholder(self) -> None:
        result = _build_contributor_commits_chart([])
        assert "chart-empty" in result

    def test_single_contributor_returns_chart(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=15)]
        result = _build_contributor_commits_chart(ranked)
        assert "<div" in result

    def test_multiple_contributors_return_chart(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=30),
            _make_ranked("Bob", commit_count=12),
            _make_ranked("Carol", commit_count=5),
        ]
        result = _build_contributor_commits_chart(ranked)
        assert "<div" in result


@pytest.mark.unit
class TestBuildContributorLinesChart:
    """Tests for the grouped lines changed bar chart builder."""

    def test_empty_ranked_returns_placeholder(self) -> None:
        result = _build_contributor_lines_chart([])
        assert "chart-empty" in result

    def test_single_contributor_returns_chart(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=10, lines_added=500, lines_deleted=80)]
        result = _build_contributor_lines_chart(ranked)
        assert "<div" in result

    def test_multiple_contributors_return_chart(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20, lines_added=1200, lines_deleted=300),
            _make_ranked("Bob", commit_count=8, lines_added=400, lines_deleted=100),
        ]
        result = _build_contributor_lines_chart(ranked)
        assert "<div" in result
