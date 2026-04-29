"""Contributor ranking engine.

Assigns each contributor a composite score and tier designation based
on configurable weighted metrics. Rankings are relative to the
contributor population within a single analysis window -- no absolute
thresholds are applied.

Tier designations applied by percentile:
    I    Recruit            0th  -- 20th
    II   Operative          21st -- 40th
    III  Specialist         41st -- 60th
    IV   Senior Specialist  61st -- 75th
    V    Lead               76th -- 88th
    VI   Principal          89th -- 95th
    VII  Commander          96th -- 100th

Default metric weights:
    commit_volume    0.30  -- Raw commit count, normalised within population.
    lines            0.25  -- Total lines changed, normalised.
    consistency      0.25  -- Active days divided by total days in window.
    recency          0.20  -- Exponentially decayed commit frequency,
                              favouring recent activity over historical volume.
"""

from __future__ import annotations

import datetime

from reveille.config import RankingWeights
from reveille.domain.models import ContributorStats, RankedContributor

# Tier boundaries: (minimum percentile exclusive, tier number, designation).
# Evaluated top-down; the first matching entry is applied.
_TIER_BOUNDARIES: list[tuple[float, int, str]] = [
    (95.0, 7, "Commander"),
    (88.0, 6, "Principal"),
    (75.0, 5, "Lead"),
    (60.0, 4, "Senior Specialist"),
    (40.0, 3, "Specialist"),
    (20.0, 2, "Operative"),
    (0.0,  1, "Recruit"),
]


def rank_contributors(
    contributors: list[ContributorStats],
    weights: RankingWeights,
    window_start: datetime.date,
    window_end: datetime.date,
) -> list[RankedContributor]:
    """Compute composite scores and assign tier designations to all contributors.

    Args:
        contributors: Aggregated stats for each contributor in the analysis
            window. Must contain at least one entry.
        weights: Configured metric weights. Must sum to 1.0.
        window_start: First date of the analysis window, inclusive.
        window_end: Last date of the analysis window, inclusive.

    Returns:
        A list of RankedContributor instances sorted by composite_score
        descending (highest score first).

    Raises:
        ValueError: If contributors is empty.

    Note:
        Implementation scheduled for feat/ranking-engine.
    """
    raise NotImplementedError(
        "rank_contributors is not yet implemented. "
        "Scheduled for feat/ranking-engine."
    )


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
        raise ValueError(
            f"percentile must be in [0.0, 100.0], got {percentile}."
        )
    for threshold, tier, designation in _TIER_BOUNDARIES:
        if percentile > threshold:
            return tier, designation
    return 1, "Recruit"
