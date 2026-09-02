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

# Version of the structured-output contract, independent of the release
# version. Consumers parse `schema_version` to decide whether they can read a
# payload. It changes only when the shape changes, and v0.7.0 proved why it is
# needed: `derived.bus_factor` was renamed to `derived.commit_concentration`
# with no way for a consumer to detect the change except a KeyError at runtime.
#
# Bump the major on any removal or rename; bump the minor on a purely additive
# field. See docs/adr/0008-output-provenance-and-schema-version.md.
SCHEMA_VERSION = "1.0"


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
    """Metadata describing the target repository and the analysis window.

    `analysed_branch` is the ref the analysis actually walked. It was called
    `default_branch` through v0.7.0 and held neither the default branch nor the
    analysed one -- it was recomputed from whatever happened to be checked out,
    so a report produced with `--branch` named the wrong ref in both the HTML
    and the JSON. See ADR 0005 for the precedent: a label with an established
    meaning attached to a different quantity is a defect, not a naming quibble.
    """

    name: str
    remote_url: str | None
    analysed_branch: str
    total_commits: int
    unique_contributors: int
    analysis_since: datetime.date
    analysis_until: datetime.date
    generated_at: datetime.datetime


@dataclass(frozen=True)
class AnalysisProvenance:
    """How a report was produced: the tool, the exact input, and the filters.

    A report states numbers; provenance states what those numbers measured.
    Without it two reports that disagree cannot be reconciled, because nothing
    records whether they differed in filters, in window, in ranking weights, or
    in the repository state itself.

    The distinction between `requested_*` and the resolved values in
    `RepositoryMetadata` is deliberate. `analysis_since` records where the
    window *began*; `requested_since` records whether anybody *asked* for that.
    A reader cannot otherwise tell "the full history, which starts in March"
    from "filtered to start in March".
    """

    reveille_version: str
    schema_version: str
    head_sha: str | None
    requested_branch: str | None
    requested_since: datetime.date | None
    requested_until: datetime.date | None
    # A count, not the values. `--exclude-author` exists to keep a person out
    # of the report; writing their address into a labelled provenance field
    # puts it back, and promotes it from one row among many to something
    # greppable. The count still distinguishes a filtered report from an
    # unfiltered one, which is all provenance needs.
    exclude_authors_count: int
    min_commits: int
    ranking_enabled: bool
    ranking_weights: dict[str, float] | None
    mailmap_applied: bool
    deterministic: bool


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
    provenance: AnalysisProvenance
    ranked_contributors: list[RankedContributor]
    commits: list[Commit] = field(default_factory=list)
