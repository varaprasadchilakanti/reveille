"""Contributor ranking engine.

Assigns each contributor a composite score and tier designation based
on configurable weighted metrics. Rankings are relative to the
contributor population within a single analysis window -- no absolute
thresholds are applied.

Normalisation is min-max within the population for each metric except
consistency, which is already bounded to [0.0, 1.0] as a ratio. When
the population contains only one contributor, all normalised scores
resolve to 1.0 and the contributor receives the Commander designation
by definition.

Recency is computed as an exponentially decayed commit frequency. Each
contributor's commits are binned by calendar week. The most recent week
in the analysis window receives a weight of 1.0; each prior week is
discounted by a decay factor of 0.85. This rewards sustained recent
activity over historical volume while remaining fully reproducible from
the raw commit timestamps.

Tier designations applied by percentile rank:
    I    Private     0th  -- 20th
    II   Corporal    21st -- 40th
    III  Sergeant    41st -- 60th
    IV   Lieutenant  61st -- 75th
    V    Captain     76th -- 88th
    VI   Major       89th -- 95th
    VII  Commander   96th -- 100th

Default metric weights (must sum to 1.0):
    commit_volume    0.30
    lines            0.25
    consistency      0.25
    recency          0.20
"""

from __future__ import annotations

import bisect
import datetime
from collections import defaultdict

from reveille.config import RankingWeights
from reveille.domain.models import Commit, ContributorStats, RankedContributor

# Recency decay applied per calendar week moving back from the most recent week.
_RECENCY_DECAY: float = 0.85

# Tier boundaries evaluated top-down. The first entry whose threshold
# is strictly less than the contributor's percentile is applied.
# Format: (exclusive lower bound, tier number, designation)
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
    ),  # Exhaustive fallback. Matches all percentiles in [0.0, 100.0].
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
        contributors: Aggregated stats for each contributor in the analysis
            window. Must contain at least one entry.
        commits: Raw commit list for the same window, used to compute
            per-contributor recency scores.
        weights: Configured metric weights. Must sum to 1.0.
        window_start: First date of the analysis window, inclusive.
        window_end: Last date of the analysis window, inclusive.

    Returns:
        A list of RankedContributor instances sorted by composite_score
        descending (highest score first).

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
        percentile: A value in the range [0.0, 100.0] representing the
            contributor's position within the ranked population.

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


# ------------------------------------------------------------------
# Private computation helpers
# ------------------------------------------------------------------


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
    """Compute the four raw metric values for each contributor.

    Consistency is computed as active_days / total_days and is already
    normalised to [0.0, 1.0]. The remaining three metrics are raw counts
    and volumes requiring subsequent min-max normalisation.

    Args:
        contributors: Contributor stats for the analysis window.
        commit_index: Commits grouped by lowercased author email.
        total_days: Total calendar days in the analysis window.
        window_end: End of the analysis window, used as the recency anchor.

    Returns:
        A dict mapping lowercased email to a dict of metric name to raw value.
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

    Commits are binned by ISO calendar week. The week containing
    window_end receives a weight of 1.0. Each prior week is multiplied
    by _RECENCY_DECAY per week of distance. The score is the sum of
    (commit_count_in_week * week_weight) across all weeks.

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
        # Compute week distance as approximate days / 7.
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

    Consistency is already in [0.0, 1.0] and is passed through unchanged.
    When all contributors share an identical value for a metric (max == min),
    all normalised values for that metric resolve to 1.0.

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

    Uses a lower-bound percentile rank formula. For each contributor,
    the rank is the number of other contributors with a strictly lower
    composite score (bisect_left on the sorted score list). Contributors
    with identical composite scores receive the same lower-bound percentile.
    For a population of one, the single contributor receives the 100th
    percentile.

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
