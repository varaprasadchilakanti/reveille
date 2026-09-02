# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Core domain models for Reveille.

Pure Python dataclasses with no framework dependencies, no I/O,
and no knowledge of Git, HTML, or CLI concerns. These are the
lingua franca passed between all layers of the application.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Commit:
    """A single Git commit reduced to the fields relevant for analysis."""

    sha: str
    author_name: str
    author_email: str
    timestamp: datetime.datetime
    lines_added: int
    lines_deleted: int

    @property
    def lines_changed(self) -> int:
        """Total lines touched by this commit (additions + deletions)."""
        return self.lines_added + self.lines_deleted


@dataclass(frozen=True)
class ContributorStats:
    """Aggregated activity metrics for a single contributor within an analysis window.

    Produced by the git reader from raw Commit objects.
    """

    name: str
    email: str
    commit_count: int
    lines_added: int
    lines_deleted: int
    active_days: int
    first_commit_date: datetime.date
    last_commit_date: datetime.date

    @property
    def net_lines(self) -> int:
        """Net lines contributed (additions minus deletions)."""
        return self.lines_added - self.lines_deleted

    @property
    def lines_changed(self) -> int:
        """Total lines touched (additions plus deletions)."""
        return self.lines_added + self.lines_deleted


@dataclass(frozen=True)
class RankedContributor:
    """A ContributorStats instance augmented with ranking information.

    Includes the composite score and tier designation assigned by
    the ranking engine.
    """

    stats: ContributorStats
    composite_score: float
    percentile: float
    tier: int
    tier_designation: str


@dataclass(frozen=True)
class RepositoryMetadata:
    """Metadata describing the target repository and the analysis window."""

    name: str
    remote_url: str | None
    default_branch: str
    total_commits: int
    unique_contributors: int
    analysis_since: datetime.date
    analysis_until: datetime.date
    generated_at: datetime.datetime


@dataclass(frozen=True)
class ProgressEvent:
    """A pipeline progress notification emitted at each stage boundary.

    Carries the name of the stage that is starting, the elapsed time
    of the stage that just completed, and an optional item count from
    the completed stage.
    """

    stage: str
    elapsed_seconds: float
    items_processed: int | None = None


@dataclass
class ReportData:
    """The complete structured dataset for a single report.

    This is the output of the application service and the sole input
    to the renderer. It contains everything the template requires to
    produce the HTML output with no further computation.
    """

    metadata: RepositoryMetadata
    ranked_contributors: list[RankedContributor]
    commits: list[Commit] = field(default_factory=list)
