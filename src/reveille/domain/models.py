# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Core domain models: plain dataclasses passed between every layer.

No I/O and no knowledge of Git, HTML or the CLI.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

# Structured-output contract version, independent of the release (ADR 0008).
# Major on any removal or rename; minor on a purely additive field.
SCHEMA_VERSION = "1.2"


@dataclass(frozen=True)
class Commit:
    """A single Git commit reduced to the fields relevant for analysis."""

    sha: str
    author_name: str
    author_email: str
    timestamp: datetime.datetime
    lines_added: int
    lines_deleted: int
    #: `(name, address)` credited by `Co-authored-by`; never authorship (ADR 0014).
    co_authors: tuple[tuple[str, str], ...] = ()

    @property
    def lines_changed(self) -> int:
        """Total lines touched by this commit (additions + deletions)."""
        return self.lines_added + self.lines_deleted


@dataclass(frozen=True)
class FileStats:
    """Activity recorded against one path, pooled across contributors.

    Identifies no person, which is why it is in the default report.

    Attributes:
        path: Repository-relative path, renames resolved to the destination.
        commits: Number of commits that touched this path.
        lines_added: Lines added to this path across those commits.
        lines_deleted: Lines deleted from this path across those commits.
    """

    path: str
    commits: int
    lines_added: int
    lines_deleted: int

    @property
    def lines_changed(self) -> int:
        """Total churn: added plus deleted, not net."""
        return self.lines_added + self.lines_deleted


@dataclass(frozen=True)
class ContributorStats:
    """Aggregated activity metrics for one contributor within the window."""

    name: str
    email: str
    commit_count: int
    lines_added: int
    lines_deleted: int
    active_days: int
    first_commit_date: datetime.date
    last_commit_date: datetime.date
    #: Commits credited as co-author (ADR 0014); never part of the ranking.
    co_authored_commits: int = 0

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
    """ContributorStats with the composite score, percentile and tier assigned."""

    stats: ContributorStats
    composite_score: float
    percentile: float
    tier: int
    tier_designation: str


@dataclass(frozen=True)
class RepositoryMetadata:
    """Metadata describing the target repository and the analysis window.

    `analysed_branch` is the ref the analysis actually walked, not the default
    branch.
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

    Lets two disagreeing reports be reconciled. `requested_*` records what was
    asked for; `RepositoryMetadata` holds the resolved window, so "history
    starts in March" differs from "filtered to start in March".
    """

    reveille_version: str
    schema_version: str
    head_sha: str | None
    requested_branch: str | None
    requested_since: datetime.date | None
    requested_until: datetime.date | None
    # A count, not the addresses: recording them would put excluded people back.
    exclude_authors_count: int
    min_commits: int
    ranking_enabled: bool
    ranking_weights: dict[str, float] | None
    mailmap_applied: bool
    deterministic: bool
    # Commits dated after a default window's end (wrong clock, rebase); counted
    # in no figure, recorded so the omission is never silent.
    commits_dated_after_window: int = 0
    # Unreadable commit records (ADR 0019); counted in no figure.
    commits_unreadable: int = 0
    # Merge commits in the selection (ADR 0001); counted in no figure.
    merge_commits_excluded: int = 0
    # Figures then describe the clone, not the project.
    shallow_clone: bool = False
    # Replace refs and grafts not followed (ADR 0018); `git log` would follow them.
    replace_refs_not_followed: int = 0
    graft_file_not_followed: bool = False
    # Whether area authors were asked for, and at what depth (ADR 0013).
    area_authors_enabled: bool = False
    area_depth: int | None = None
    # Cap on any list of people in JSON or CSV (ADR 0015); None for no cap.
    limit: int | None = None
    # Paths left out of every figure, as given; paths name no one.
    exclude_paths: tuple[str, ...] = ()
    # Every address replaced by a per-report token (`--hide-emails`).
    emails_hidden: bool = False


@dataclass(frozen=True)
class CoAuthor:
    """An identity credited only as a co-author in the window (ADR 0014).

    Attributes:
        name: Display name, resolved like an author's.
        email: Lower-cased address, the identity key.
        co_authored_commits: Commits whose trailers credit this identity.
    """

    name: str
    email: str
    co_authored_commits: int


@dataclass(frozen=True)
class AreaActivity:
    """Who changed one directory in the analysis window (ADR 0013).

    An area, not a person: deliberately no count per person.

    Attributes:
        area: The directory, at most `--area-depth` components, or "(root)".
        commits: Commits that changed at least one file in the area.
        last_changed: The date of the most recent of those commits.
        authors: Lower-cased address to last-change date; only chooses which
            names to show, never output (it would read as a departure date).
        first_changed: The date of the earliest of those commits.
    """

    area: str
    commits: int
    last_changed: datetime.date
    authors: dict[str, datetime.date]
    first_changed: datetime.date | None = None


@dataclass(frozen=True)
class ProgressEvent:
    """A progress notification at each pipeline stage boundary.

    Attributes:
        stage: The stage starting.
        elapsed_seconds: Duration of the stage just completed.
        items_processed: Optional item count from the completed stage.
    """

    stage: str
    elapsed_seconds: float
    items_processed: int | None = None


@dataclass
class ReportData:
    """The complete structured dataset for a single report.

    The service's output and the renderer's sole input; needs no further
    computation.
    """

    metadata: RepositoryMetadata
    provenance: AnalysisProvenance
    ranked_contributors: list[RankedContributor]
    commits: list[Commit] = field(default_factory=list)
    #: Per-path activity; empty omits the file sections.
    file_stats: list[FileStats] = field(default_factory=list)
    #: Held back by `min_commits`, which filters the listing, not the analysis:
    #: every derived figure still includes them.
    suppressed_contributors: list[ContributorStats] = field(default_factory=list)
    #: Per-directory activity, only with `--area-authors` (ADR 0013).
    areas: list[AreaActivity] = field(default_factory=list)
    #: Identities credited only as co-authors, alphabetically (ADR 0014).
    co_authors_only: list[CoAuthor] = field(default_factory=list)
