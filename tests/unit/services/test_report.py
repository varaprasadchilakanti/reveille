"""Unit tests for reveille.services.report.

The application service is an orchestrator with no logic of its own
beyond wiring. These tests verify the orchestration contracts using
mocks, confirming that the service calls its collaborators correctly
and handles their outputs as expected.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from reveille.config import ReportConfig
from reveille.domain.models import (
    Commit,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)
from reveille.services.report import generate_report

# ------------------------------------------------------------------
# Shared fixtures
# ------------------------------------------------------------------

@pytest.fixture()
def minimal_config(tmp_path: Path) -> ReportConfig:
    """A minimal ReportConfig pointing at a temp directory."""
    return ReportConfig(
        repo_path=tmp_path,
        output_path=tmp_path / "report.html",
        since=datetime.date(2024, 1, 1),
        until=datetime.date(2024, 3, 31),
        ranking_enabled=True,
    )


@pytest.fixture()
def sample_commit() -> Commit:
    """A single Commit instance for use in service unit tests."""
    return Commit(
        sha="abc123",
        author_name="Alice",
        author_email="alice@example.com",
        timestamp=datetime.datetime(2024, 2, 15, 10, 0, tzinfo=datetime.UTC),
        lines_added=30,
        lines_deleted=5,
    )


@pytest.fixture()
def sample_stats(sample_commit: Commit) -> ContributorStats:
    """A single ContributorStats instance derived from sample_commit."""
    return ContributorStats(
        name="Alice",
        email="alice@example.com",
        commit_count=1,
        lines_added=30,
        lines_deleted=5,
        active_days=1,
        first_commit_date=datetime.date(2024, 2, 15),
        last_commit_date=datetime.date(2024, 2, 15),
    )


@pytest.fixture()
def sample_ranked(sample_stats: ContributorStats) -> RankedContributor:
    """A RankedContributor at the Commander tier for use in service tests."""
    return RankedContributor(
        stats=sample_stats,
        composite_score=1.0,
        percentile=100.0,
        tier=7,
        tier_designation="Commander",
    )


@pytest.fixture()
def sample_metadata() -> RepositoryMetadata:
    """A RepositoryMetadata instance for use in service tests."""
    return RepositoryMetadata(
        name="test-repo",
        remote_url=None,
        default_branch="main",
        total_commits=1,
        unique_contributors=1,
        analysis_since=datetime.date(2024, 1, 1),
        analysis_until=datetime.date(2024, 3, 31),
        generated_at=datetime.datetime(
            2024, 4, 1, 12, 0, tzinfo=datetime.UTC
        ),
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

@pytest.mark.unit
class TestGenerateReport:
    """Tests for the generate_report orchestration function."""

    def test_returns_output_path_from_renderer(
        self,
        minimal_config: ReportConfig,
        sample_commit: Commit,
        sample_stats: ContributorStats,
        sample_ranked: RankedContributor,
        sample_metadata: RepositoryMetadata,
        tmp_path: Path,
    ) -> None:
        expected_path = tmp_path / "report.html"

        with (
            patch("reveille.services.report.GitReader") as mock_reader,
            patch("reveille.services.report.rank_contributors") as mock_rank,
            patch("reveille.services.report.Renderer") as mock_renderer,
        ):
            reader_instance = mock_reader.return_value
            reader_instance.read_commits.return_value = [sample_commit]
            reader_instance.aggregate_contributor_stats.return_value = [sample_stats]
            reader_instance.read_metadata.return_value = sample_metadata
            mock_rank.return_value = [sample_ranked]
            mock_renderer.return_value.render.return_value = expected_path

            result = generate_report(minimal_config)

        assert result == expected_path

    def test_rank_contributors_called_when_ranking_enabled(
        self,
        minimal_config: ReportConfig,
        sample_commit: Commit,
        sample_stats: ContributorStats,
        sample_ranked: RankedContributor,
        sample_metadata: RepositoryMetadata,
    ) -> None:
        with (
            patch("reveille.services.report.GitReader") as mock_reader,
            patch("reveille.services.report.rank_contributors") as mock_rank,
            patch("reveille.services.report.Renderer") as mock_renderer,
        ):
            reader_instance = mock_reader.return_value
            reader_instance.read_commits.return_value = [sample_commit]
            reader_instance.aggregate_contributor_stats.return_value = [sample_stats]
            reader_instance.read_metadata.return_value = sample_metadata
            mock_rank.return_value = [sample_ranked]
            mock_renderer.return_value.render.return_value = Path("out.html")

            generate_report(minimal_config)

        mock_rank.assert_called_once()

    def test_rank_contributors_not_called_when_ranking_disabled(
        self,
        tmp_path: Path,
        sample_commit: Commit,
        sample_stats: ContributorStats,
        sample_metadata: RepositoryMetadata,
    ) -> None:
        config = ReportConfig(
            repo_path=tmp_path,
            output_path=tmp_path / "report.html",
            since=datetime.date(2024, 1, 1),
            until=datetime.date(2024, 3, 31),
            ranking_enabled=False,
        )
        with (
            patch("reveille.services.report.GitReader") as mock_reader,
            patch("reveille.services.report.rank_contributors") as mock_rank,
            patch("reveille.services.report.Renderer") as mock_renderer,
        ):
            reader_instance = mock_reader.return_value
            reader_instance.read_commits.return_value = [sample_commit]
            reader_instance.aggregate_contributor_stats.return_value = [sample_stats]
            reader_instance.read_metadata.return_value = sample_metadata
            mock_renderer.return_value.render.return_value = Path("out.html")

            generate_report(config)

        mock_rank.assert_not_called()

    def test_title_override_replaces_metadata_name(
        self,
        tmp_path: Path,
        sample_commit: Commit,
        sample_stats: ContributorStats,
        sample_ranked: RankedContributor,
        sample_metadata: RepositoryMetadata,
    ) -> None:
        config = ReportConfig(
            repo_path=tmp_path,
            output_path=tmp_path / "report.html",
            since=datetime.date(2024, 1, 1),
            until=datetime.date(2024, 3, 31),
            title="Q1 Engineering Report",
        )
        captured: list[ReportData] = []

        with (
            patch("reveille.services.report.GitReader") as mock_reader,
            patch("reveille.services.report.rank_contributors") as mock_rank,
            patch("reveille.services.report.Renderer") as mock_renderer,
        ):
            reader_instance = mock_reader.return_value
            reader_instance.read_commits.return_value = [sample_commit]
            reader_instance.aggregate_contributor_stats.return_value = [sample_stats]
            reader_instance.read_metadata.return_value = sample_metadata
            mock_rank.return_value = [sample_ranked]

            def capture_render(
                data: ReportData,
                path: Path,
                heatmap_granularity: str = "monthly",
            ) -> Path:
                captured.append(data)
                return path

            mock_renderer.return_value.render.side_effect = capture_render

            generate_report(config)

        assert len(captured) == 1
        assert captured[0].metadata.name == "Q1 Engineering Report"

    def test_window_start_uses_config_since_when_provided(
        self,
        minimal_config: ReportConfig,
        sample_commit: Commit,
        sample_stats: ContributorStats,
        sample_ranked: RankedContributor,
        sample_metadata: RepositoryMetadata,
    ) -> None:
        with (
            patch("reveille.services.report.GitReader") as mock_reader,
            patch("reveille.services.report.rank_contributors") as mock_rank,
            patch("reveille.services.report.Renderer") as mock_renderer,
        ):
            reader_instance = mock_reader.return_value
            reader_instance.read_commits.return_value = [sample_commit]
            reader_instance.aggregate_contributor_stats.return_value = [sample_stats]
            reader_instance.read_metadata.return_value = sample_metadata
            mock_rank.return_value = [sample_ranked]
            mock_renderer.return_value.render.return_value = Path("out.html")

            generate_report(minimal_config)

        call_kwargs = reader_instance.aggregate_contributor_stats.call_args
        assert call_kwargs.kwargs["window_start"] == datetime.date(2024, 1, 1)

    def test_renderer_receives_commits_in_report_data(
        self,
        minimal_config: ReportConfig,
        sample_commit: Commit,
        sample_stats: ContributorStats,
        sample_ranked: RankedContributor,
        sample_metadata: RepositoryMetadata,
    ) -> None:
        captured: list[ReportData] = []

        with (
            patch("reveille.services.report.GitReader") as mock_reader,
            patch("reveille.services.report.rank_contributors") as mock_rank,
            patch("reveille.services.report.Renderer") as mock_renderer,
        ):
            reader_instance = mock_reader.return_value
            reader_instance.read_commits.return_value = [sample_commit]
            reader_instance.aggregate_contributor_stats.return_value = [sample_stats]
            reader_instance.read_metadata.return_value = sample_metadata
            mock_rank.return_value = [sample_ranked]

            def capture(
                data: ReportData,
                path: Path,
                heatmap_granularity: str = "monthly",
            ) -> Path:
                captured.append(data)
                return path

            mock_renderer.return_value.render.side_effect = capture

            generate_report(minimal_config)

        assert captured[0].commits == [sample_commit]
