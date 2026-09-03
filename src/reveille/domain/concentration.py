# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""How evenly activity is distributed across contributors.

This module answers a question about a *repository*, not about the people in
it: is the work spread across the team, or carried by a few? That distinction
is why it survives the ranking being off by default. The Lorenz curve and the
Gini coefficient describe a distribution; neither names anybody, and neither
can be read as a judgement of an individual.

Both are borrowed rather than invented, which is the point of using them. The
Lorenz curve (Lorenz, 1905) and the Gini coefficient (Gini, 1912) are the
standard instruments for concentration in a population, with a century of
economics behind their interpretation and their known weaknesses. Reveille
previously reported only "how many contributors account for a majority of
commits" -- a number with no literature behind it, no defined range, and a
step change in value whenever one contributor crosses 50%.

**What the Gini coefficient does not mean here.** It measures the shape of a
distribution, nothing more. A high value is not a problem to be fixed and a low
one is not a goal: a repository with one author has a Gini of 0 by definition,
and a healthy project with a maintainer and many drive-by contributors will
score high for entirely benign reasons. It is a description, and it is only
comparable against the same repository over time or against a repository of
similar shape.
"""

from __future__ import annotations


def lorenz_curve(values: list[int]) -> list[tuple[float, float]]:
    """Return the Lorenz curve for a set of non-negative quantities.

    The curve plots the cumulative share of the population against the
    cumulative share of the total, with the population sorted from smallest to
    largest. The diagonal from (0, 0) to (1, 1) is perfect equality; the
    further the curve bows beneath it, the more concentrated the distribution.

    Args:
        values: Per-contributor quantities, such as commit counts. Order is
            irrelevant; the function sorts. Values must not be negative.

    Returns:
        Points from (0.0, 0.0) to (1.0, 1.0) inclusive, so a caller can plot
        the curve directly against the diagonal. An empty input, or one summing
        to zero, returns just the two endpoints -- there is no distribution to
        describe, and inventing intermediate points would imply one.

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

    Computed with the standard discrete formula over the sorted sample::

        G = (2 * sum(i * x_i)) / (n * sum(x)) - (n + 1) / n

    where `x` is sorted ascending and `i` runs from 1 to n.

    Args:
        values: Per-contributor quantities. Order is irrelevant.

    Returns:
        A value in [0, 1]. Zero means every contributor holds an equal share --
        which includes the single-contributor case, where equality is trivially
        true. The maximum for a sample of n is (n - 1) / n, approaching but
        never reaching 1: one contributor holding everything in a group of four
        gives 0.75, not 1.0. That ceiling is a property of the sample size, not
        a defect, and it is why the value should not be compared across
        repositories with very different contributor counts.

        An empty input, or one summing to zero, returns 0.0: no distribution
        exists, and reporting inequality where there is no quantity would be a
        stronger claim than the data supports.

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

    # Floating-point error can push a perfectly equal distribution a hair below
    # zero. Clamping is honest here: the formula's range is [0, 1] and a
    # negative Gini has no meaning to report.
    return max(0.0, coefficient)
