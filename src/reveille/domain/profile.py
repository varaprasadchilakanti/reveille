# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A three-axis profile of a repository's working pattern.

Every axis is a **naturally bounded ratio** -- a share of something out of
something -- so nothing is rescaled by a constant chosen to make a figure
look right. That constraint is the whole design.

**Why three and not five.** Two axes were removed at 0.9.0 because each
restated a number the report already prints elsewhere:

* `Spread` was exactly ``1 - Gini / ((n-1)/n)``, a monotone transform of the
  Gini coefficient shown in the Contribution Distribution section a few
  hundred pixels above, with better caveats attached to it there. It also
  returned a hard-coded 0.0 for a single contributor, described as "nothing
  to spread", which plotted *undefined* at the same position as *worst
  possible*.
* `Small steps` was exactly the first three buckets of the change-size
  histogram summed -- the threshold was chosen to match that boundary -- so
  it could not tell a different story, only the same one twice.

A consequence worth stating: the profile no longer reads contributor data at
all. It describes the repository's working pattern and cannot name, rank or
count people even accidentally.

**Expected values are computed, never chosen.** Two of the three axes have an
expectation that follows from their own arithmetic, and the report shows it so
a reader can tell an ordinary value from a notable one:

* `Continuity` under commits placed uniformly at random across the window is
  ``1 - (1 - 1/W)**C`` for C commits over W weeks.
* `Recent work` measures the share of commits in the window's final quarter,
  so its expectation under even activity is the share of days that quarter
  occupies -- close to 0.25, and computed exactly rather than assumed,
  because the cut-off is inclusive.
* `Revisiting` has no such expectation. It is shown without one rather than
  given an invented figure.

That distinction is load-bearing. A computed expectation is a fact about how
the measure is built. A number somebody thinks is *good* would be a target,
and none of these axes is a target: a repository can score low on all three
for entirely ordinary reasons -- a finished library, a spike, a
single-maintainer tool -- and this is a description, not a scorecard.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from reveille.domain.files import is_generated
from reveille.domain.models import Commit, FileStats

#: Fixed axis order. Part of the contract: a reader comparing two reports of
#: the same repository should find the measures in the same places.
AXIS_ORDER = ("Continuity", "Recent work", "Revisiting")


@dataclass(frozen=True)
class ProfileAxis:
    """One axis of the repository profile.

    Attributes:
        name: The axis label, one of `AXIS_ORDER`.
        value: A share between 0.0 and 1.0.
        description: What the share is of, in one clause, so a reader can
            check the number rather than trust it.
        expected: The value this axis takes under evenly spread activity,
            where that follows from the measure's own arithmetic, else
            None. Never a target, and never a figure anyone chose.
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

    The expectation is the share of weeks that would contain a commit if the
    same number of commits were placed uniformly at random: one minus the
    chance that a given week is missed by all of them. Without it a reader
    has no way to tell a high-looking number from an ordinary one -- this
    repository reads 0.913 against an expectation of about 0.99, so the
    figure that looks strong is in fact below par.
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

    This replaced an axis that measured where the last commit sat inside the
    window. Under `--deterministic` the window *ends* at the last commit, so
    that axis was identically 100% for every repository ever analysed -- in
    precisely the mode the Playbook tells consumers to use.

    The expectation is the share of the window's days that the final quarter
    occupies. It is computed rather than assumed to be 0.25: the cut-off is
    inclusive, so the quarter is one day longer than a quarter.
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

    A repository whose files are written once and never returned to looks
    different from one being iterated on. Generated files are excluded
    because a lock file's revision count reflects tooling, not work.

    No expectation is offered. One would depend on how long the repository
    has existed and how many files it has, neither of which this measure
    knows, and a figure invented to fill the gap would read as a target.
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


def repository_profile(
    commits: list[Commit],
    files: list[FileStats],
    since: datetime.date,
    until: datetime.date,
) -> list[ProfileAxis]:
    """Return the three profile axes, always in `AXIS_ORDER`.

    Takes no contributor data: since `Spread` was removed the profile
    describes the repository's working pattern and never looks at people.

    Args:
        commits: Every commit in the analysis window.
        files: Per-path activity for the window.
        since: First day of the analysis window.
        until: Last day of the analysis window.

    Returns:
        Three axes in the fixed documented order. Empty if there are no
        commits, since a profile of nothing says nothing.
    """
    if not commits:
        return []

    axes = [
        _continuity(commits, since, until),
        _recent_share(commits, since, until),
        _revisiting(files),
    ]
    ordered = {axis.name: axis for axis in axes}
    return [ordered[name] for name in AXIS_ORDER]
