# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A minimal `ReportData` for renderer tests, built from commit counts alone."""

from __future__ import annotations

import datetime

from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)

PROVENANCE = AnalysisProvenance(
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


def report_data(counts: list[int]) -> ReportData:
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
        provenance=PROVENANCE,
        ranked_contributors=ranked(counts),
        commits=[],
    )


def ranked(counts: list[int]) -> list[RankedContributor]:
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
