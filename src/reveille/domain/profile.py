# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A six-axis profile of a repository's working pattern (ADR 0012, 0016).

Every axis is a naturally bounded ratio, so nothing is rescaled by a chosen
constant. Axes read authors and trailers only to count commits; none names,
ranks or counts one person's work. Where an expected value follows from the
measure's own arithmetic it is shown; otherwise none is invented. A
description, not a scorecard: no axis is a target.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from reveille.domain.areas import is_automated
from reveille.domain.files import is_generated
from reveille.domain.models import Commit, FileStats

#: Fixed axis order, part of the contract so reports compare like for like.
AXIS_ORDER = (
    "Continuity",
    "Recent work",
    "Shared",
    "Collaboration",
    "Revisiting",
    "Automation",
)


@dataclass(frozen=True)
class ProfileAxis:
    """One axis of the repository profile.

    Attributes:
        name: The axis label, one of `AXIS_ORDER`.
        value: A share between 0.0 and 1.0.
        description: What the share is of, in one clause.
        expected: The value under evenly spread activity, where the arithmetic
            gives one, else None. Never a target.
    """

    name: str
    value: float
    description: str
    expected: float | None = None


def _continuity(
    commits: list[Commit],
    since: datetime.date,
    until: datetime.date,
) -> ProfileAxis:
    """Share of the window's weeks containing at least one commit.

    Expected under uniformly random placement: 1 - (1 - 1/W)**C for C commits
    over W weeks.
    """
    total_weeks = max(((until - since).days // 7) + 1, 1)
    in_window = [c for c in commits if since <= c.timestamp.date() <= until]
    active = {(c.timestamp.date() - since).days // 7 for c in in_window}
    expected = 1.0 - (1.0 - 1.0 / total_weeks) ** len(in_window)
    return ProfileAxis(
        name="Continuity",
        value=min(len(active) / total_weeks, 1.0),
        description="weeks in the window with at least one commit",
        expected=min(expected, 1.0),
    )


def _recent_share(
    commits: list[Commit],
    since: datetime.date,
    until: datetime.date,
) -> ProfileAxis:
    """Share of commits falling in the most recent quarter of the window.

    Expected: the share of days the final quarter occupies, computed rather
    than assumed 0.25 because the cut-off is inclusive.
    """
    span = max((until - since).days, 1)
    cutoff = until - datetime.timedelta(days=span // 4)
    in_window = [c for c in commits if since <= c.timestamp.date() <= until]
    recent = sum(1 for c in in_window if c.timestamp.date() >= cutoff)
    return ProfileAxis(
        name="Recent work",
        value=recent / len(in_window) if in_window else 0.0,
        description="commits in the final quarter of the window",
        expected=(span // 4 + 1) / (span + 1),
    )


def _revisiting(files: list[FileStats]) -> ProfileAxis:
    """Share of hand-written files touched by more than one commit.

    Generated files are excluded: their revisions reflect tooling. No
    expectation: it would depend on age and file count, which are unknown here.
    """
    written = [f for f in files if not is_generated(f.path)]
    if not written:
        return ProfileAxis(
            name="Revisiting",
            value=0.0,
            description="files touched by more than one commit",
        )
    revisited = sum(1 for f in written if f.commits > 1)
    return ProfileAxis(
        name="Revisiting",
        value=revisited / len(written),
        description="files touched by more than one commit",
    )


def _shared(commits: list[Commit]) -> ProfileAxis:
    """Share of people's commits not made by the busiest person (ADR 0016).

    Automated accounts are excluded from both sides; their share is
    `Automation`'s. Expected under an even split across n people: 1 - 1/n.
    None without human commits.
    """
    counts: dict[str, int] = {}
    for commit in commits:
        if is_automated(commit.author_name, commit.author_email):
            continue
        email = commit.author_email.lower()
        counts[email] = counts.get(email, 0) + 1
    description = "commits by people not made by the busiest person"
    if not counts:
        return ProfileAxis(name="Shared", value=0.0, description=description)
    return ProfileAxis(
        name="Shared",
        value=1.0 - max(counts.values()) / sum(counts.values()),
        description=description,
        expected=1.0 - 1.0 / len(counts),
    )


def _collaboration(commits: list[Commit]) -> ProfileAxis:
    """Share of commits that credit a co-author (ADR 0014, 0016).

    No expectation: there is no arithmetic baseline.
    """
    return ProfileAxis(
        name="Collaboration",
        value=sum(1 for c in commits if c.co_authors) / len(commits),
        description="commits that credit a co-author",
    )


def _automation(commits: list[Commit]) -> ProfileAxis:
    """Share of commits made by automated accounts (ADR 0013's rule, 0016).

    No expectation and no judgement.
    """
    return ProfileAxis(
        name="Automation",
        value=sum(1 for c in commits if is_automated(c.author_name, c.author_email)) / len(commits),
        description="commits by automated accounts",
    )


def repository_profile(
    commits: list[Commit],
    files: list[FileStats],
    since: datetime.date,
    until: datetime.date,
) -> list[ProfileAxis]:
    """Return the six profile axes, always in `AXIS_ORDER`.

    Shares of the repository's work, never any one person's.

    Args:
        commits: Every commit in the analysis window.
        files: Per-path activity for the window.
        since: First day of the analysis window.
        until: Last day of the analysis window.

    Returns:
        Six axes in `AXIS_ORDER`, or empty when there are no commits.
    """
    if not commits:
        return []

    axes = [
        _continuity(commits, since, until),
        _recent_share(commits, since, until),
        _shared(commits),
        _collaboration(commits),
        _revisiting(files),
        _automation(commits),
    ]
    ordered = {axis.name: axis for axis in axes}
    return [ordered[name] for name in AXIS_ORDER]
