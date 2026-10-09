# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
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
SCHEMA_VERSION = "1.1"


@dataclass(frozen=True)
class Commit:
    """A single Git commit reduced to the fields relevant for analysis."""

    sha: str
    author_name: str
    author_email: str
    timestamp: datetime.datetime
    lines_added: int
    lines_deleted: int
    #: `(name, address)` of each identity a `Co-authored-by` trailer credits,
    #: resolved like an author (ADR 0014). Never counted as authorship.
    co_authors: tuple[tuple[str, str], ...] = ()

    @property
    def lines_changed(self) -> int:
        """Total lines touched by this commit (additions + deletions)."""
        return self.lines_added + self.lines_deleted


@dataclass(frozen=True)
class FileStats:
    """Activity recorded against one path, pooled across contributors.

    A file, not a person. Nothing here identifies who changed what, which
    is why it is in the default report at all.

    Attributes:
        path: The file path, relative to the repository root, after any
            rename has been resolved to its destination.
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
    #: Commits this contributor is credited on as a co-author (ADR 0014). A
    #: plain count beside the authored one; never part of the ranking.
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
    # Commits dated after the end of a default window -- a wrong clock, or a
    # rebase that kept a future date. They are counted in no figure; this is
    # where that is recorded, so the report never silently holds fewer
    # commits than the branch.
    commits_dated_after_window: int = 0
    # Commits Git reported whose record could not be read (ADR 0019). Counted
    # in no figure, and recorded so the omission is never silent.
    commits_unreadable: int = 0
    # A shallow clone holds only its most recent commits. Every figure then
    # describes the clone, not the project, and the window starts where the
    # clone's history does.
    shallow_clone: bool = False
    # Whether the "who changed each area" section was asked for, and at what
    # depth (ADR 0013). Recorded either way, so a report states that it does
    # not name people by area as plainly as one that does.
    area_authors_enabled: bool = False
    area_depth: int | None = None
    # The most entries any list of people in JSON or CSV carries (ADR 0015),
    # or None for every one.
    limit: int | None = None


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

    An area, not a person: it records which identities changed it and when
    it was last changed, and deliberately no count per person, which would
    be a share of the area per person.

    Attributes:
        area: The directory, at most `--area-depth` components, or "(root)"
            for files at the top level.
        commits: Commits that changed at least one file in the area.
        last_changed: The date of the most recent of those commits.
        authors: Lower-cased address of everybody who made them, mapped to
            the date they last changed the area. Used only to choose which
            names a long list shows; never printed or written out, since a
            person's last date reads as a departure date.
    """

    area: str
    commits: int
    last_changed: datetime.date
    authors: dict[str, datetime.date]


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
    #: Per-path activity, pooled across contributors. Defaults to empty so
    #: a caller constructing a report without it -- every existing test --
    #: keeps working; the file sections are then simply absent.
    file_stats: list[FileStats] = field(default_factory=list)
    #: Contributors held back from the listing by `min_commits`. They are
    #: still part of the repository, so every derived figure is computed
    #: over these as well as the listed ones -- `min_commits` filters the
    #: listing, not the analysis. Defaults to empty, so a caller
    #: constructing a report without it keeps working.
    suppressed_contributors: list[ContributorStats] = field(default_factory=list)
    #: Per-directory activity, present only when `--area-authors` asked for
    #: it (ADR 0013). Empty otherwise, and the section is then absent.
    areas: list[AreaActivity] = field(default_factory=list)
    #: Identities credited only as co-authors, alphabetically (ADR 0014).
    co_authors_only: list[CoAuthor] = field(default_factory=list)
