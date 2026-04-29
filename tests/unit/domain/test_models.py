"""Unit tests for reveille.domain.models.

These tests cover the computed properties on domain model classes.
All tests run in-process with no I/O.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.models import Commit, ContributorStats


@pytest.mark.unit
class TestCommit:
    """Tests for the Commit domain model."""

    def test_lines_changed_is_sum_of_additions_and_deletions(self) -> None:
        commit = Commit(
            sha="abc123",
            author_name="Alice",
            author_email="alice@example.com",
            timestamp=datetime.datetime(2024, 6, 1, 10, 0, tzinfo=datetime.UTC),
            lines_added=30,
            lines_deleted=10,
        )
        assert commit.lines_changed == 40

    def test_lines_changed_with_zero_deletions(self) -> None:
        commit = Commit(
            sha="def456",
            author_name="Bob",
            author_email="bob@example.com",
            timestamp=datetime.datetime(2024, 6, 2, 9, 0, tzinfo=datetime.UTC),
            lines_added=15,
            lines_deleted=0,
        )
        assert commit.lines_changed == 15

    def test_lines_changed_with_zero_additions(self) -> None:
        commit = Commit(
            sha="ghi789",
            author_name="Carol",
            author_email="carol@example.com",
            timestamp=datetime.datetime(2024, 6, 3, 8, 0, tzinfo=datetime.UTC),
            lines_added=0,
            lines_deleted=20,
        )
        assert commit.lines_changed == 20

    def test_commit_is_immutable(self) -> None:
        commit = Commit(
            sha="abc123",
            author_name="Alice",
            author_email="alice@example.com",
            timestamp=datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC),
            lines_added=10,
            lines_deleted=5,
        )
        with pytest.raises(AttributeError):
            commit.sha = "mutated"  # type: ignore[misc]


@pytest.mark.unit
class TestContributorStats:
    """Tests for the ContributorStats domain model."""

    def test_net_lines_is_additions_minus_deletions(
        self, sample_contributor_stats: ContributorStats
    ) -> None:
        assert sample_contributor_stats.net_lines == 1800 - 400

    def test_lines_changed_is_additions_plus_deletions(
        self, sample_contributor_stats: ContributorStats
    ) -> None:
        assert sample_contributor_stats.lines_changed == 1800 + 400

    def test_net_lines_is_negative_when_deletions_exceed_additions(self) -> None:
        stats = ContributorStats(
            name="Refactorer",
            email="ref@example.com",
            commit_count=10,
            lines_added=100,
            lines_deleted=500,
            active_days=5,
            first_commit_date=datetime.date(2024, 1, 1),
            last_commit_date=datetime.date(2024, 1, 31),
        )
        assert stats.net_lines == -400

    def test_contributor_stats_is_immutable(
        self, sample_contributor_stats: ContributorStats
    ) -> None:
        with pytest.raises(AttributeError):
            sample_contributor_stats.commit_count = 999  # type: ignore[misc]
