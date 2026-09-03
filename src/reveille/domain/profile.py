# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A five-axis profile of a repository's working pattern.

Every axis here is a **naturally bounded ratio** -- a share of something
out of something -- so nothing is rescaled by a constant chosen to make
the shape look right. That constraint is the whole design. A radar chart
whose axes are normalised by invented scaling factors can be given any
silhouette its author wants, and the reader has no way to tell.

The chart form is contentious and deserves its caveats stated rather than
hidden. A radar encodes by **area**, which sits near the bottom of
Cleveland and McGill's ranking of graphical perception (*Graphical
Perception: Theory, Experimentation, and Application to the Development
of Graphical Methods*, JASA 1984) -- position and length are read far
more accurately. Worse, the enclosed area depends on the **order** of the
axes, which carries no meaning: permuting two axes changes the shape
without changing a single number. So:

* the axis order is fixed and documented here, never data-dependent;
* every vertex is labelled with its own value, so the figure can be read
  as five numbers rather than as a silhouette;
* the report states that the area means nothing.

What it is good at is the thing it is used for here: showing at a glance
which axes are high and which are low, and being recognisable against the
same repository at a later date.

None of these axes is a target. A repository can score low on all five
for entirely ordinary reasons -- a finished library, a spike, a
single-maintainer tool -- and this is a description, not a scorecard. No
axis measures a person.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from reveille.domain.concentration import gini_coefficient
from reveille.domain.files import is_generated
from reveille.domain.models import Commit, ContributorStats, FileStats

#: Change size, in lines, at or below which a commit counts as a small
#: step. Chosen to match the third bucket boundary of the change-size
#: histogram so the two sections cannot tell different stories.
_SMALL_COMMIT_LINES = 200

#: Fixed axis order. Permuting these changes the drawn shape without
#: changing any value, so the order is part of the contract.
AXIS_ORDER = ("Spread", "Continuity", "Currency", "Revisiting", "Small steps")


@dataclass(frozen=True)
class ProfileAxis:
    """One axis of the repository profile.

    Attributes:
        name: The axis label, one of `AXIS_ORDER`.
        value: A share between 0.0 and 1.0.
        description: What the share is of, in one clause, so a reader can
            check the number rather than trust it.
    """

    name: str
    value: float
    description: str


def _spread(contributors: list[ContributorStats]) -> ProfileAxis:
    """How evenly commits are distributed across contributors."""
    counts = [c.commit_count for c in contributors]
    value = 1.0 - gini_coefficient(counts) if len(counts) > 1 else 0.0
    return ProfileAxis(
        name="Spread",
        value=value,
        description="1 minus the Gini over commits per contributor",
    )


def _continuity(
    commits: list[Commit],
    since: datetime.date,
    until: datetime.date,
) -> ProfileAxis:
    """Share of the window's weeks containing at least one commit."""
    total_weeks = max(((until - since).days // 7) + 1, 1)
    active = {
        (c.timestamp.date() - since).days // 7
        for c in commits
        if since <= c.timestamp.date() <= until
    }
    return ProfileAxis(
        name="Continuity",
        value=min(len(active) / total_weeks, 1.0),
        description="weeks in the window with at least one commit",
    )


def _currency(
    commits: list[Commit],
    since: datetime.date,
    until: datetime.date,
) -> ProfileAxis:
    """How far through the window the most recent commit falls."""
    span = max((until - since).days, 1)
    last = max((c.timestamp.date() for c in commits), default=since)
    return ProfileAxis(
        name="Currency",
        value=min(max((last - since).days / span, 0.0), 1.0),
        description="position of the last commit within the window",
    )


def _revisiting(files: list[FileStats]) -> ProfileAxis:
    """Share of hand-written files touched by more than one commit.

    A repository whose files are written once and never returned to looks
    different from one being iterated on. Generated files are excluded
    because a lock file's revision count reflects tooling, not work.
    """
    written = [f for f in files if not is_generated(f.path)]
    if not written:
        return ProfileAxis(name="Revisiting", value=0.0, description="files touched more than once")
    revisited = sum(1 for f in written if f.commits > 1)
    return ProfileAxis(
        name="Revisiting",
        value=revisited / len(written),
        description="files touched by more than one commit",
    )


def _small_steps(commits: list[Commit]) -> ProfileAxis:
    """Share of commits changing fewer than `_SMALL_COMMIT_LINES` lines."""
    if not commits:
        return ProfileAxis(
            name="Small steps", value=0.0, description="commits under 200 lines changed"
        )
    small = sum(1 for c in commits if c.lines_added + c.lines_deleted < _SMALL_COMMIT_LINES)
    return ProfileAxis(
        name="Small steps",
        value=small / len(commits),
        description=f"commits changing fewer than {_SMALL_COMMIT_LINES} lines",
    )


def repository_profile(
    commits: list[Commit],
    contributors: list[ContributorStats],
    files: list[FileStats],
    since: datetime.date,
    until: datetime.date,
) -> list[ProfileAxis]:
    """Return the five profile axes, always in `AXIS_ORDER`.

    Args:
        commits: Every commit in the analysis window.
        contributors: Aggregated per-contributor statistics.
        files: Per-path activity for the window.
        since: First day of the analysis window.
        until: Last day of the analysis window.

    Returns:
        Five axes in the fixed documented order. Empty if there are no
        commits, since a profile of nothing is a shape that says nothing.
    """
    if not commits:
        return []

    axes = [
        _spread(contributors),
        _continuity(commits, since, until),
        _currency(commits, since, until),
        _revisiting(files),
        _small_steps(commits),
    ]
    ordered = {axis.name: axis for axis in axes}
    return [ordered[name] for name in AXIS_ORDER]
