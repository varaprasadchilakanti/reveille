# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Contributor ranking: weighted composite score, percentile and tier.

Measures volume and regularity of commits, not contribution; never assess
individuals with it (SPACE, Forsgren et al., 2021). Opt-in (ADR 0010).
Min-max within one window; lower-bound percentile (ADR 0003). Tier names are
labels on a score of commit volume and regularity, not an evaluation of anyone:

    I Private 0-20   II Corporal 21-40   III Sergeant 41-60   IV Lieutenant 61-75
    V Captain 76-88  VI Major 89-95      VII Commander 96-100

Default weights, a documented judgement, not a derived model (`RankingWeights`):
commits 0.30, lines 0.25, consistency 0.25, recency 0.20.
"""

from __future__ import annotations

import bisect
import datetime
from collections import defaultdict

from reveille.config import RankingWeights
from reveille.domain.models import Commit, ContributorStats, RankedContributor

# Recency decay applied per calendar week moving back from the most recent week.
_RECENCY_DECAY: float = 0.85

# (exclusive lower bound, tier, designation), evaluated top-down; the first
# threshold strictly below the percentile applies.
_TIER_BOUNDARIES: list[tuple[float, int, str]] = [
    (95.0, 7, "Commander"),
    (88.0, 6, "Major"),
    (75.0, 5, "Captain"),
    (60.0, 4, "Lieutenant"),
    (40.0, 3, "Sergeant"),
    (20.0, 2, "Corporal"),
    (
        -1.0,
        1,
        "Private",
    ),  # Exhaustive fallback for [0.0, 100.0].
]


def rank_contributors(
    contributors: list[ContributorStats],
    commits: list[Commit],
    weights: RankingWeights,
    window_start: datetime.date,
    window_end: datetime.date,
) -> list[RankedContributor]:
    """Compute composite scores and assign tier designations to all contributors.

    Args:
        contributors: Stats per contributor in the window; at least one.
        commits: Commits in the same window, for recency.
        weights: Configured metric weights. Must sum to 1.0.
        window_start: First date of the window, inclusive.
        window_end: Last date of the window, inclusive.

    Returns:
        RankedContributor instances, highest composite_score first.

    Raises:
        ValueError: If contributors is empty.
    """
    if not contributors:
        raise ValueError(
            "rank_contributors requires at least one contributor. "
            "Apply min_commits filtering before calling this function."
        )

    total_days = max((window_end - window_start).days, 1)
    commit_index = _build_commit_index(commits)

    raw_scores = _compute_raw_scores(contributors, commit_index, total_days, window_end)
    normalised = _normalise_scores(raw_scores)
    composite = _compute_composite(normalised, weights)
    percentiles = _compute_percentiles(composite)

    ranked = []
    for contributor in contributors:
        email = contributor.email.lower()
        score = composite[email]
        percentile = percentiles[email]
        tier, designation = assign_tier(percentile)
        ranked.append(
            RankedContributor(
                stats=contributor,
                composite_score=round(score, 6),
                percentile=round(percentile, 2),
                tier=tier,
                tier_designation=designation,
            )
        )

    return sorted(ranked, key=lambda r: r.composite_score, reverse=True)


def assign_tier(percentile: float) -> tuple[int, str]:
    """Map a percentile value to a tier number and designation.

    Args:
        percentile: Position within the population, in [0.0, 100.0].

    Returns:
        A tuple of (tier_number, tier_designation).

    Raises:
        ValueError: If percentile is outside the range [0.0, 100.0].
    """
    if not 0.0 <= percentile <= 100.0:
        raise ValueError(f"percentile must be in [0.0, 100.0], got {percentile}.")
    for threshold, tier, designation in _TIER_BOUNDARIES:
        if percentile > threshold:
            return tier, designation
    raise AssertionError(
        f"No tier boundary matched percentile {percentile}. "
        "_TIER_BOUNDARIES must contain an exhaustive fallback entry with a "
        "threshold strictly below 0.0."
    )


# Private computation helpers.


def _build_commit_index(commits: list[Commit]) -> dict[str, list[Commit]]:
    """Group commits by lowercased author email for O(1) lookup.

    Args:
        commits: Raw commit list for the analysis window.

    Returns:
        A dict mapping lowercased email to the contributor's commits.
    """
    index: dict[str, list[Commit]] = defaultdict(list)
    for commit in commits:
        index[commit.author_email.lower()].append(commit)
    return dict(index)


def _compute_raw_scores(
    contributors: list[ContributorStats],
    commit_index: dict[str, list[Commit]],
    total_days: int,
    window_end: datetime.date,
) -> dict[str, dict[str, float]]:
    """Compute the four raw metrics; consistency = active_days / total_days.

    Args:
        contributors: Contributor stats for the analysis window.
        commit_index: Commits grouped by lowercased author email.
        total_days: Total calendar days in the analysis window.
        window_end: End of the analysis window, used as the recency anchor.

    Returns:
        Lowercased email to {metric name: raw value}.
    """
    raw: dict[str, dict[str, float]] = {}
    for contributor in contributors:
        email = contributor.email.lower()
        contributor_commits = commit_index.get(email, [])
        raw[email] = {
            "commits": float(contributor.commit_count),
            "lines": float(contributor.lines_changed),
            "consistency": contributor.active_days / total_days,
            "recency": _compute_recency_score(contributor_commits, window_end),
        }
    return raw


def _compute_recency_score(
    commits: list[Commit],
    window_end: datetime.date,
) -> float:
    """Compute an exponentially decayed commit frequency score.

    Sum over ISO weeks of commits * _RECENCY_DECAY ** weeks before the week
    containing window_end.

    Args:
        commits: All commits for a single contributor in the analysis window.
        window_end: The anchor date from which decay is measured.

    Returns:
        A non-negative float. Zero if the contributor has no commits.
    """
    if not commits:
        return 0.0

    anchor_week = window_end.isocalendar()[:2]  # (year, week)
    weekly_counts: dict[tuple[int, int], int] = defaultdict(int)
    for commit in commits:
        week_key = commit.timestamp.date().isocalendar()[:2]
        weekly_counts[week_key] += 1

    score = 0.0
    for (year, week), count in weekly_counts.items():
        anchor_date = datetime.date.fromisocalendar(anchor_week[0], anchor_week[1], 1)
        commit_date = datetime.date.fromisocalendar(year, week, 1)
        weeks_ago = max((anchor_date - commit_date).days // 7, 0)
        weight = _RECENCY_DECAY**weeks_ago
        score += count * weight

    return score


def _normalise_scores(
    raw: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Apply min-max normalisation to commits, lines, and recency metrics.

    Consistency passes through unchanged. A metric where max == min
    normalises to 1.0 for everyone.

    Args:
        raw: Raw metric values keyed by lowercased email.

    Returns:
        A dict with the same structure where every value is in [0.0, 1.0].
    """
    metrics = ["commits", "lines", "recency"]
    min_max: dict[str, tuple[float, float]] = {}
    for metric in metrics:
        values = [raw[email][metric] for email in raw]
        min_max[metric] = (min(values), max(values))

    normalised: dict[str, dict[str, float]] = {}
    for email, scores in raw.items():
        normalised[email] = {"consistency": scores["consistency"]}
        for metric in metrics:
            lo, hi = min_max[metric]
            if hi == lo:
                normalised[email][metric] = 1.0
            else:
                normalised[email][metric] = (scores[metric] - lo) / (hi - lo)

    return normalised


def _compute_composite(
    normalised: dict[str, dict[str, float]],
    weights: RankingWeights,
) -> dict[str, float]:
    """Compute the weighted composite score for each contributor.

    Args:
        normalised: Normalised metric scores in [0.0, 1.0] per contributor.
        weights: Configured metric weights.

    Returns:
        A dict mapping lowercased email to composite score in [0.0, 1.0].
    """
    composite: dict[str, float] = {}
    for email, scores in normalised.items():
        composite[email] = (
            scores["commits"] * weights.commits
            + scores["lines"] * weights.lines
            + scores["consistency"] * weights.consistency
            + scores["recency"] * weights.recency
        )
    return composite


def _compute_percentiles(composite: dict[str, float]) -> dict[str, float]:
    """Assign a percentile rank to each contributor based on composite score.

    Lower-bound rank via bisect_left, so ties share a percentile (ADR 0003).
    A population of one is the 100th percentile.

    Args:
        composite: Composite scores keyed by lowercased email.

    Returns:
        A dict mapping lowercased email to percentile in [0.0, 100.0].
    """
    emails = list(composite.keys())
    n = len(emails)
    if n == 1:
        return {emails[0]: 100.0}

    sorted_scores = sorted(composite.values())
    percentiles: dict[str, float] = {}
    for email, score in composite.items():
        rank = bisect.bisect_left(sorted_scores, score)
        percentiles[email] = round((rank / (n - 1)) * 100.0, 2)
    return percentiles
