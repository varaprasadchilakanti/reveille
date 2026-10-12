# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""How evenly commits are distributed across contributors.

Describes the repository, not its people: neither measure names anybody, so it
stays on when the ranking is off. Lorenz curve (Lorenz, 1905); Gini coefficient
(Gini, 1912). Concentration is not a bus factor. A high Gini is not a problem
and a low one not a goal; compare only against the same or a similar repository.
"""

from __future__ import annotations


def lorenz_curve(values: list[int]) -> list[tuple[float, float]]:
    """Return the Lorenz curve for a set of non-negative quantities.

    Cumulative population share against cumulative total share, sorted
    ascending; the diagonal is perfect equality.

    Args:
        values: Per-contributor quantities, any order, none negative.

    Returns:
        Points from (0.0, 0.0) to (1.0, 1.0) inclusive; only the two endpoints
        when the input is empty or sums to zero.

    Raises:
        ValueError: If any value is negative.
    """
    if any(v < 0 for v in values):
        raise ValueError("Lorenz curve is undefined for negative quantities.")

    total = sum(values)
    if not values or total == 0:
        return [(0.0, 0.0), (1.0, 1.0)]

    ordered = sorted(values)
    count = len(ordered)

    points: list[tuple[float, float]] = [(0.0, 0.0)]
    cumulative = 0
    for index, value in enumerate(ordered, start=1):
        cumulative += value
        points.append((index / count, cumulative / total))
    return points


def gini_coefficient(values: list[int]) -> float:
    """Return the Gini coefficient of a set of non-negative quantities.

    Discrete formula over x sorted ascending, i from 1 to n:
    G = 2 * sum(i * x_i) / (n * sum(x)) - (n + 1) / n.

    Args:
        values: Per-contributor quantities, any order.

    Returns:
        A value in [0, (n - 1) / n]; 0.0 for equal shares, one contributor, an
        empty input or a zero total. The ceiling depends on n, so do not compare
        repositories with very different contributor counts.

    Raises:
        ValueError: If any value is negative.
    """
    if any(v < 0 for v in values):
        raise ValueError("Gini coefficient is undefined for negative quantities.")

    total = sum(values)
    count = len(values)
    if count == 0 or total == 0:
        return 0.0

    ordered = sorted(values)
    weighted = sum(index * value for index, value in enumerate(ordered, start=1))
    coefficient = (2 * weighted) / (count * total) - (count + 1) / count

    # Floating-point error can push an equal distribution just below zero.
    return max(0.0, coefficient)
