"""Unit tests for reveille.domain.ranking.

All tests run in-process with no I/O. The fixture repository used
in integration tests is not required here -- inputs are constructed
directly from domain model constructors.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.config import RankingWeights
from reveille.domain.models import Commit, ContributorStats, RankedContributor
from reveille.domain.ranking import (
    _compute_percentiles,
    _compute_recency_score,
    _normalise_scores,
    assign_tier,
    rank_contributors,
)

# ------------------------------------------------------------------
# Shared fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def default_weights() -> RankingWeights:
    """Default RankingWeights with documented production values."""
    return RankingWeights()


@pytest.fixture()
def window_start() -> datetime.date:
    return datetime.date(2024, 1, 1)


@pytest.fixture()
def window_end() -> datetime.date:
    return datetime.date(2024, 3, 31)


def _make_stats(
    email: str,
    commit_count: int,
    lines_added: int = 100,
    lines_deleted: int = 20,
    active_days: int = 10,
    first: datetime.date | None = None,
    last: datetime.date | None = None,
) -> ContributorStats:
    """Construct a ContributorStats instance with sensible defaults."""
    return ContributorStats(
        name=email.split("@")[0].capitalize(),
        email=email,
        commit_count=commit_count,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        active_days=active_days,
        first_commit_date=first or datetime.date(2024, 1, 5),
        last_commit_date=last or datetime.date(2024, 3, 20),
    )


def _make_commit(
    email: str,
    date: datetime.date,
    lines_added: int = 10,
    lines_deleted: int = 2,
) -> Commit:
    """Construct a Commit instance for a given author and date."""
    return Commit(
        sha=f"{email[:4]}{date.isoformat()}",
        author_name=email.split("@")[0].capitalize(),
        author_email=email,
        timestamp=datetime.datetime(
            date.year,
            date.month,
            date.day,
            12,
            0,
            0,
            tzinfo=datetime.UTC,
        ),
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )


# ------------------------------------------------------------------
# assign_tier
# ------------------------------------------------------------------


@pytest.mark.unit
class TestAssignTier:
    """Tests for the assign_tier function."""

    @pytest.mark.parametrize(
        "percentile, expected_tier, expected_designation",
        [
            (0.0, 1, "Recruit"),
            (10.0, 1, "Recruit"),
            (20.0, 1, "Recruit"),
            (21.0, 2, "Operative"),
            (40.0, 2, "Operative"),
            (41.0, 3, "Specialist"),
            (60.0, 3, "Specialist"),
            (61.0, 4, "Senior Specialist"),
            (75.0, 4, "Senior Specialist"),
            (76.0, 5, "Lead"),
            (88.0, 5, "Lead"),
            (89.0, 6, "Principal"),
            (95.0, 6, "Principal"),
            (96.0, 7, "Commander"),
            (100.0, 7, "Commander"),
        ],
    )
    def test_tier_assignment_at_boundary_and_midpoint(
        self,
        percentile: float,
        expected_tier: int,
        expected_designation: str,
    ) -> None:
        tier, designation = assign_tier(percentile)
        assert tier == expected_tier
        assert designation == expected_designation

    def test_below_zero_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="percentile must be in"):
            assign_tier(-0.1)

    def test_above_one_hundred_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="percentile must be in"):
            assign_tier(100.1)


# ------------------------------------------------------------------
# rank_contributors
# ------------------------------------------------------------------


@pytest.mark.unit
class TestRankContributors:
    """Tests for the rank_contributors orchestration function."""

    def test_empty_contributors_raises_value_error(
        self,
        default_weights: RankingWeights,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> None:
        with pytest.raises(ValueError, match="at least one contributor"):
            rank_contributors(
                contributors=[],
                commits=[],
                weights=default_weights,
                window_start=window_start,
                window_end=window_end,
            )

    def test_returns_ranked_contributor_for_each_input(
        self,
        default_weights: RankingWeights,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> None:
        contributors = [
            _make_stats("alice@example.com", commit_count=20),
            _make_stats("bob@example.com", commit_count=8),
        ]
        commits = [
            _make_commit("alice@example.com", datetime.date(2024, 3, 1)),
            _make_commit("bob@example.com", datetime.date(2024, 2, 1)),
        ]
        result = rank_contributors(
            contributors=contributors,
            commits=commits,
            weights=default_weights,
            window_start=window_start,
            window_end=window_end,
        )
        assert len(result) == 2
        assert all(isinstance(r, RankedContributor) for r in result)

    def test_result_is_sorted_by_composite_score_descending(
        self,
        default_weights: RankingWeights,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> None:
        contributors = [
            _make_stats("alice@example.com", commit_count=50, lines_added=3000),
            _make_stats("bob@example.com", commit_count=5, lines_added=100),
        ]
        commits = [
            _make_commit("alice@example.com", datetime.date(2024, 3, 20)),
            _make_commit("bob@example.com", datetime.date(2024, 1, 5)),
        ]
        result = rank_contributors(
            contributors=contributors,
            commits=commits,
            weights=default_weights,
            window_start=window_start,
            window_end=window_end,
        )
        scores = [r.composite_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_single_contributor_receives_commander_designation(
        self,
        default_weights: RankingWeights,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> None:
        contributors = [_make_stats("solo@example.com", commit_count=10)]
        commits = [_make_commit("solo@example.com", datetime.date(2024, 2, 1))]
        result = rank_contributors(
            contributors=contributors,
            commits=commits,
            weights=default_weights,
            window_start=window_start,
            window_end=window_end,
        )
        assert result[0].tier == 7
        assert result[0].tier_designation == "Commander"

    def test_composite_score_is_bounded_to_unit_interval(
        self,
        default_weights: RankingWeights,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> None:
        contributors = [
            _make_stats("a@example.com", commit_count=100, lines_added=10000),
            _make_stats("b@example.com", commit_count=1, lines_added=5),
        ]
        commits = [
            _make_commit("a@example.com", datetime.date(2024, 3, 25)),
            _make_commit("b@example.com", datetime.date(2024, 1, 2)),
        ]
        result = rank_contributors(
            contributors=contributors,
            commits=commits,
            weights=default_weights,
            window_start=window_start,
            window_end=window_end,
        )
        for ranked in result:
            assert 0.0 <= ranked.composite_score <= 1.0

    def test_percentile_is_bounded_to_zero_to_one_hundred(
        self,
        default_weights: RankingWeights,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> None:
        contributors = [
            _make_stats("a@example.com", commit_count=30),
            _make_stats("b@example.com", commit_count=15),
            _make_stats("c@example.com", commit_count=5),
        ]
        commits = [
            _make_commit("a@example.com", datetime.date(2024, 3, 1)),
            _make_commit("b@example.com", datetime.date(2024, 2, 1)),
            _make_commit("c@example.com", datetime.date(2024, 1, 15)),
        ]
        result = rank_contributors(
            contributors=contributors,
            commits=commits,
            weights=default_weights,
            window_start=window_start,
            window_end=window_end,
        )
        for ranked in result:
            assert 0.0 <= ranked.percentile <= 100.0


# ------------------------------------------------------------------
# _compute_recency_score
# ------------------------------------------------------------------


@pytest.mark.unit
class TestComputeRecencyScore:
    """Tests for the recency scoring helper."""

    def test_empty_commits_returns_zero(self) -> None:
        score = _compute_recency_score([], datetime.date(2024, 3, 31))
        assert score == 0.0

    def test_recent_commit_scores_higher_than_older_commit(self) -> None:
        anchor = datetime.date(2024, 3, 31)
        recent = [_make_commit("a@x.com", datetime.date(2024, 3, 25))]
        older = [_make_commit("a@x.com", datetime.date(2024, 1, 5))]
        assert _compute_recency_score(recent, anchor) > _compute_recency_score(
            older, anchor
        )

    def test_score_is_non_negative(self) -> None:
        anchor = datetime.date(2024, 3, 31)
        commits = [
            _make_commit("a@x.com", datetime.date(2024, 2, 10)),
            _make_commit("a@x.com", datetime.date(2024, 3, 1)),
        ]
        assert _compute_recency_score(commits, anchor) >= 0.0


# ------------------------------------------------------------------
# _normalise_scores
# ------------------------------------------------------------------


@pytest.mark.unit
class TestNormaliseScores:
    """Tests for the min-max normalisation helper."""

    def test_all_values_identical_normalises_to_one(self) -> None:
        raw = {
            "a@x.com": {
                "commits": 10.0,
                "lines": 100.0,
                "consistency": 0.5,
                "recency": 5.0,
            },
            "b@x.com": {
                "commits": 10.0,
                "lines": 100.0,
                "consistency": 0.3,
                "recency": 5.0,
            },
        }
        result = _normalise_scores(raw)
        assert result["a@x.com"]["commits"] == 1.0
        assert result["b@x.com"]["commits"] == 1.0

    def test_max_contributor_normalises_commits_to_one(self) -> None:
        raw = {
            "a@x.com": {
                "commits": 50.0,
                "lines": 500.0,
                "consistency": 0.8,
                "recency": 10.0,
            },
            "b@x.com": {
                "commits": 10.0,
                "lines": 100.0,
                "consistency": 0.2,
                "recency": 2.0,
            },
        }
        result = _normalise_scores(raw)
        assert result["a@x.com"]["commits"] == 1.0
        assert result["b@x.com"]["commits"] == 0.0

    def test_consistency_passes_through_unchanged(self) -> None:
        raw = {
            "a@x.com": {
                "commits": 20.0,
                "lines": 200.0,
                "consistency": 0.65,
                "recency": 4.0,
            },
        }
        result = _normalise_scores(raw)
        assert result["a@x.com"]["consistency"] == pytest.approx(0.65)


# ------------------------------------------------------------------
# _compute_percentiles
# ------------------------------------------------------------------


@pytest.mark.unit
class TestComputePercentiles:
    """Tests for the percentile computation helper."""

    def test_single_contributor_receives_one_hundred(self) -> None:
        result = _compute_percentiles({"a@x.com": 0.75})
        assert result["a@x.com"] == 100.0

    def test_lowest_score_receives_zero_percentile(self) -> None:
        result = _compute_percentiles(
            {
                "a@x.com": 0.9,
                "b@x.com": 0.5,
                "c@x.com": 0.1,
            }
        )
        assert result["c@x.com"] == 0.0

    def test_highest_score_receives_one_hundred_percentile(self) -> None:
        result = _compute_percentiles(
            {
                "a@x.com": 0.9,
                "b@x.com": 0.5,
                "c@x.com": 0.1,
            }
        )
        assert result["a@x.com"] == 100.0

    def test_all_percentiles_are_bounded(self) -> None:
        scores = {f"user{i}@x.com": float(i) for i in range(10)}
        result = _compute_percentiles(scores)
        for p in result.values():
            assert 0.0 <= p <= 100.0
