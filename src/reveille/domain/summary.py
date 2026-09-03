# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A written summary of a repository's history, generated from its numbers.

This is data-to-text generation in the sense of Reiter and Dale,
*Building Natural Language Generation Systems* (2000): content is
selected by rules over computed statistics, and realised through fixed
templates. There is no model, no inference and no network call. The same
history always produces the same sentences, which is what makes the
output checkable -- every claim below is a threshold over a number that
appears elsewhere in the same report.

What it deliberately does not do:

* name an individual, or say anything evaluative about one. The findings
  are properties of the repository, in the terms ADR 0010 sets out;
* describe a number as good, bad, healthy or concerning. A finding
  states what the history shows and, where a reading is commonly drawn
  from it wrongly, says so;
* extrapolate. Nothing here predicts.

The vocabulary is deliberately small. A reader who wants the detail has
the charts; this exists so that the first fifteen seconds of reading are
spent on findings rather than on axis labels.
"""

from __future__ import annotations

import datetime
import itertools
import statistics
from dataclasses import dataclass

from reveille.domain.concentration import gini_coefficient
from reveille.domain.models import Commit, ContributorStats

#: A Gini at or above this is described as concentrated. Chosen to match
#: the point at which the Lorenz curve is visibly bowed rather than any
#: external benchmark: the coefficient is comparable against a repository
#: over time, not against another repository.
_CONCENTRATION_THRESHOLD = 0.40

#: Below this many commits, distribution and cadence findings are
#: withheld. A Gini over five commits is arithmetic, not evidence.
_MINIMUM_COMMITS_FOR_SHAPE = 20

#: A gap in calendar days that is worth naming rather than a normal pause.
_QUIET_PERIOD_DAYS = 30

#: Share of commits landing on Saturday or Sunday, above which the
#: pattern is stated. It is stated as an observation, never as a concern:
#: time zones, contract shapes and release windows all produce it.
_WEEKEND_SHARE_THRESHOLD = 0.15

#: Below this many contributors, findings that describe *behaviour* are
#: withheld entirely.
#:
#: Omitting a name does not make a sentence non-personal. GDPR Recital 26
#: asks whether a person can be singled out by any means reasonably likely
#: to be used, and in a two-person repository "31% of commits were
#: authored at a weekend" singles somebody out at zero cost -- to their
#: own colleague, and to anyone the report is forwarded to. Volume and
#: recency say something about the repository at any size; a working
#: pattern does not.
_MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR = 3


@dataclass(frozen=True)
class Finding:
    """One statement about the repository, with the figure it rests on.

    Attributes:
        headline: The finding, in one sentence.
        detail: The qualification a careful reader needs, or an empty
            string where none applies.
        evidence: The figure the headline rests on, formatted for
            display, so a reader can find it in the charts below.
    """

    headline: str
    detail: str
    evidence: str


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """Return `singular` for one, otherwise `plural` (default: +s)."""
    if count == 1:
        return f"{count} {singular}"
    return f"{count:,} {plural or singular + 's'}"


def _span_finding(commits: list[Commit]) -> Finding:
    """State the size and span of the history that was read."""
    first = min(c.timestamp for c in commits).date()
    last = max(c.timestamp for c in commits).date()
    days = (last - first).days + 1
    active = len({c.timestamp.date() for c in commits})
    return Finding(
        headline=(
            f"{_plural(len(commits), 'commit')} over {_plural(days, 'day')}, "
            f"landing on {_plural(active, 'distinct day')}."
        ),
        detail=("Merge commits are excluded, so this is lower than raw `git log`."),
        evidence=f"{first.isoformat()} to {last.isoformat()}",
    )


def _distribution_finding(contributors: list[ContributorStats]) -> Finding | None:
    """State how commits are spread, without naming anyone."""
    if len(contributors) < 2:
        return None
    counts = sorted((c.commit_count for c in contributors), reverse=True)
    gini = gini_coefficient(counts)
    total = sum(counts)
    leading_share = counts[0] / total

    # The Gini coefficient is bounded by (n-1)/n, so with two contributors it
    # cannot exceed 0.50 however lopsided the split. Reading a raw threshold
    # over small counts produced "spread fairly evenly... the busiest holding
    # 73%" in one sentence. The leading share decides the wording; the
    # coefficient is reported as the evidence behind it.
    if len(counts) < _MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR:
        # With two contributors, a leading share is a statement about one
        # named person in a table four sections below. The Gini describes
        # the same distribution without singling anyone out.
        return Finding(
            headline=(f"Commits are distributed across {_plural(len(counts), 'contributor')}."),
            detail=(
                "The share held by each is in the table below. With so few "
                "contributors a share is a statement about an identifiable "
                "person, so it is not restated here."
            ),
            evidence=f"Gini {gini:.2f}",
        )

    if leading_share > 0.50:
        headline = (
            f"One contributor authored {leading_share:.0%} of commits, of "
            f"{_plural(len(counts), 'contributor')} in total."
        )
        detail = (
            "This describes the repository, not the people in it. One "
            "maintainer with occasional contributors produces this shape for "
            "entirely ordinary reasons, and it is not a bus factor."
        )
    elif gini >= _CONCENTRATION_THRESHOLD:
        headline = (
            f"Commits are concentrated among "
            f"{_plural(len(counts), 'contributor')}, the busiest holding "
            f"{leading_share:.0%}."
        )
        detail = (
            "Concentration is comparable against this repository over time, "
            "not against a different one."
        )
    else:
        headline = (
            f"Commits are spread across "
            f"{_plural(len(counts), 'contributor')} with no single majority; "
            f"the busiest holds {leading_share:.0%}."
        )
        detail = "An even spread is a description, not an achievement."
    return Finding(headline=headline, detail=detail, evidence=f"Gini {gini:.2f}")


def _cadence_finding(commits: list[Commit]) -> Finding | None:
    """State the rhythm of committing, and the longest quiet run."""
    if len(commits) < _MINIMUM_COMMITS_FOR_SHAPE:
        return None
    days = sorted({c.timestamp.date() for c in commits})
    if len(days) < 2:
        return None
    gaps = [(b - a).days for a, b in itertools.pairwise(days)]
    median = statistics.median(gaps)
    # A gap of n days between two active days contains n-1 days with no
    # commits. The summary card counts inactive calendar days; this once
    # counted the gap, so the two disagreed by exactly one on every
    # repository ever analysed -- "Max Inactive Days 13" beside "longest
    # quiet run of 14 days", in one document, about one fact.
    longest = max(gaps) - 1

    headline = (
        f"Typically {median:.0f} "
        f"{'day' if median == 1 else 'days'} between active days, with a "
        f"longest quiet run of {_plural(longest, 'day')}."
    )
    detail = (
        "A quiet run is not idleness: released software, holidays and work "
        "on other branches all read the same way here."
        if longest >= _QUIET_PERIOD_DAYS
        else ""
    )
    return Finding(headline=headline, detail=detail, evidence=f"median gap {median:.0f}d")


def _weekend_finding(
    commits: list[Commit],
    contributors: list[ContributorStats],
) -> Finding | None:
    """State weekend activity as an observation, never as a judgement.

    Withheld below `_MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR`. This is the most
    sensitive sentence the module can produce, and in a small repository
    it is a sentence about one identifiable person's out-of-hours working.
    """
    if len(commits) < _MINIMUM_COMMITS_FOR_SHAPE:
        return None
    if len(contributors) < _MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR:
        return None
    weekend = sum(1 for c in commits if c.timestamp.weekday() >= 5)
    share = weekend / len(commits)
    if share < _WEEKEND_SHARE_THRESHOLD:
        return None
    return Finding(
        headline=f"{share:.0%} of commits were authored at a weekend.",
        detail=(
            "Author timestamps carry the committer's own time zone, and this "
            "report normalises to it. Distributed contributors, release "
            "windows and rebases all move commits across this boundary."
        ),
        evidence=f"{weekend:,} of {len(commits):,}",
    )


def _recency_finding(commits: list[Commit], today: datetime.date) -> Finding | None:
    """State how current the history is, relative to when it was read."""
    last = max(c.timestamp for c in commits).date()
    idle = (today - last).days
    if idle < _QUIET_PERIOD_DAYS:
        return None
    return Finding(
        headline=f"No commits in the last {_plural(idle, 'day')}.",
        detail=(
            "The analysis window may simply end before the most recent work; "
            "check `--since` and `--until` before reading this as dormancy."
        ),
        evidence=f"last commit {last.isoformat()}",
    )


def summarise(
    commits: list[Commit],
    contributors: list[ContributorStats],
    today: datetime.date | None = None,
) -> list[Finding]:
    """Generate the findings for a repository, most structural first.

    Args:
        commits: Every commit in the analysis window.
        contributors: Aggregated per-contributor statistics.
        today: The date to measure recency against. Defaults to the most
            recent commit date, which keeps the output reproducible for
            `--deterministic`; pass a real date to measure dormancy.

    Returns:
        Findings in reading order. Empty if there are no commits, since
        a summary of nothing is a sentence that says nothing.
    """
    if not commits:
        return []
    reference = today or max(c.timestamp for c in commits).date()

    candidates = [
        _span_finding(commits),
        _distribution_finding(contributors),
        _cadence_finding(commits),
        _weekend_finding(commits, contributors),
        _recency_finding(commits, reference),
    ]
    return [finding for finding in candidates if finding is not None]
