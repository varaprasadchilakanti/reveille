# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A written summary of a repository's history, generated from its numbers.

Data-to-text generation (Reiter and Dale, 2000): rules over computed statistics,
fixed templates, no model or network. Same history, same sentences; every claim
is a threshold over a number in the report. Findings never name or evaluate a
person (ADR 0010), never call a number good or bad, and never predict.
"""

from __future__ import annotations

import datetime
import itertools
import statistics
from dataclasses import dataclass

from reveille.domain.concentration import gini_coefficient
from reveille.domain.models import Commit, ContributorStats

#: Gini at or above this reads as concentrated: where the Lorenz curve visibly
#: bows, not an external benchmark.
_CONCENTRATION_THRESHOLD = 0.40

#: Below this many commits, distribution and cadence findings are
#: withheld. A Gini over five commits is arithmetic, not evidence.
_MINIMUM_COMMITS_FOR_SHAPE = 20

#: A gap in calendar days that is worth naming rather than a normal pause.
_QUIET_PERIOD_DAYS = 30

#: Weekend share of commits above which the pattern is stated, as an
#: observation, never a concern.
_WEEKEND_SHARE_THRESHOLD = 0.15

#: Below this many contributors, behaviour findings are withheld: a working
#: pattern in a tiny repository singles a person out (GDPR Recital 26).
_MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR = 3


@dataclass(frozen=True)
class Finding:
    """One statement about the repository, with the figure it rests on.

    Attributes:
        headline: The finding, in one sentence.
        detail: The qualification a careful reader needs, or "".
        evidence: The figure the headline rests on, formatted for display.
    """

    headline: str
    detail: str
    evidence: str


def longest_quiet_run(commits: list[Commit]) -> int:
    """Return the most consecutive days without a commit between two that had one.

    The single definition the card, the cadence finding and the JSON share.
    Silence after the last commit belongs to the dormancy finding.

    Args:
        commits: The commits in the analysis window.

    Returns:
        Commit-free calendar days, or 0 when fewer than two days have commits.
    """
    days = sorted({c.timestamp.date() for c in commits})
    if len(days) < 2:
        return 0
    # A gap of n days between two active days holds n - 1 days with none.
    return max((b - a).days for a, b in itertools.pairwise(days)) - 1


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
        # Plain text: rendered as HTML, where backticks print literally.
        detail="Merge commits are excluded, so this is lower than a raw git log count.",
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

    # Gini is capped at (n-1)/n, so the leading share decides the wording and
    # the coefficient is the evidence.
    if len(counts) < _MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR:
        # A share would single out an identifiable person; the Gini does not.
        # `reveille summary` prints no table, so the sentence names it.
        return Finding(
            headline=(f"Commits are distributed across {_plural(len(counts), 'contributor')}."),
            detail=(
                "Each share is in the full report's contributor table. With so "
                "few contributors a share is a statement about an identifiable "
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
    longest = longest_quiet_run(commits)

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

    Withheld below `_MINIMUM_CONTRIBUTORS_FOR_BEHAVIOUR`: in a small
    repository it describes one identifiable person.
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


def _co_author_finding(commits: list[Commit]) -> Finding | None:
    """State how many commits credit a co-author, naming nobody (ADR 0014)."""
    credited = sum(1 for c in commits if c.co_authors)
    if not credited:
        return None
    return Finding(
        headline=f"{_plural(credited, 'commit')} {'credits' if credited == 1 else 'credit'} a co-author.",
        detail=(
            "Credited by a Co-authored-by trailer, which is not verified. "
            "The charts count authors only."
        ),
        evidence=f"{credited:,} of {len(commits):,}",
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
            "check --since and --until before reading this as dormancy."
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
        today: Recency reference; defaults to the latest commit date
            (reproducible); pass a real date to measure dormancy.

    Returns:
        Findings in reading order; empty when there are no commits.
    """
    if not commits:
        return []
    reference = today or max(c.timestamp for c in commits).date()

    candidates = [
        _span_finding(commits),
        _distribution_finding(contributors),
        _cadence_finding(commits),
        _weekend_finding(commits, contributors),
        _co_author_finding(commits),
        _recency_finding(commits, reference),
    ]
    return [finding for finding in candidates if finding is not None]
