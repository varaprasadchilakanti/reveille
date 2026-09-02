"""Unit tests for the Lorenz curve and Gini coefficient.

These are borrowed instruments with a century of literature behind them, which
is the reason for using them and also the reason they can be tested properly:
the expected values below are not what this implementation happens to produce,
they are what the definitions require.
"""

from __future__ import annotations

import itertools

import pytest

from reveille.domain.concentration import gini_coefficient, lorenz_curve


@pytest.mark.unit
class TestGiniCoefficient:
    """Checked against values the definition fixes, not against the code."""

    def test_perfect_equality_is_zero(self) -> None:
        """Every contributor with the same count is the definition of equal."""
        assert gini_coefficient([5, 5, 5, 5]) == 0.0

    def test_a_single_contributor_is_zero(self) -> None:
        """Equality is trivially true in a population of one.

        Worth pinning because the intuitive reading -- "one person did
        everything, so this is maximally concentrated" -- is the opposite of
        what the measure says, and a reader of the report may expect it.
        """
        assert gini_coefficient([7]) == 0.0

    def test_maximum_for_a_sample_is_n_minus_one_over_n(self) -> None:
        """One holder of everything gives (n-1)/n, never 1.0.

        The ceiling rises with sample size, which is exactly why the value must
        not be compared across repositories with very different contributor
        counts.
        """
        assert gini_coefficient([0, 0, 0, 9]) == pytest.approx(0.75)
        assert gini_coefficient([0, 9]) == pytest.approx(0.5)
        assert gini_coefficient([0] * 9 + [9]) == pytest.approx(0.9)

    def test_scale_invariance(self) -> None:
        """Multiplying every count by a constant must not change the shape."""
        assert gini_coefficient([1, 2, 3, 4]) == pytest.approx(gini_coefficient([10, 20, 30, 40]))

    def test_order_does_not_matter(self) -> None:
        """The measure is over a distribution, not a sequence."""
        assert gini_coefficient([1, 1, 2, 10]) == pytest.approx(gini_coefficient([10, 1, 2, 1]))

    def test_empty_and_all_zero_return_zero(self) -> None:
        """No quantity means no distribution; reporting inequality would overclaim."""
        assert gini_coefficient([]) == 0.0
        assert gini_coefficient([0, 0, 0]) == 0.0

    def test_result_is_always_within_range(self) -> None:
        """The formula's range is [0, 1]; floating point must not escape it."""
        for sample in ([1], [1, 1], [1, 1000000], [3, 3, 3, 3, 3, 3], [0, 1]):
            assert 0.0 <= gini_coefficient(sample) <= 1.0

    def test_negative_values_are_rejected(self) -> None:
        """The measure is undefined for negative quantities."""
        with pytest.raises(ValueError, match="negative"):
            gini_coefficient([1, -1])


@pytest.mark.unit
class TestLorenzCurve:
    """The curve must be plottable directly against the diagonal."""

    def test_equality_lies_on_the_diagonal(self) -> None:
        """Equal counts put every point on y = x."""
        assert lorenz_curve([5, 5, 5, 5]) == [
            (0.0, 0.0),
            (0.25, 0.25),
            (0.5, 0.5),
            (0.75, 0.75),
            (1.0, 1.0),
        ]

    def test_starts_at_origin_and_ends_at_one(self) -> None:
        """Both endpoints are required for the fill against the diagonal."""
        curve = lorenz_curve([1, 4, 9])

        assert curve[0] == (0.0, 0.0)
        assert curve[-1] == pytest.approx((1.0, 1.0))

    def test_is_monotonically_non_decreasing(self) -> None:
        """A Lorenz curve can never fall; that is what makes it a Lorenz curve."""
        ys = [y for _, y in lorenz_curve([9, 1, 4, 2, 7])]

        assert all(b >= a for a, b in itertools.pairwise(ys))

    def test_bows_below_the_diagonal_when_unequal(self) -> None:
        """Concentration shows as the curve sitting under y = x."""
        curve = lorenz_curve([1, 1, 1, 97])
        interior = [(x, y) for x, y in curve if 0.0 < x < 1.0]

        assert interior, "no interior points to check"
        assert all(y < x for x, y in interior)

    def test_empty_input_returns_only_the_endpoints(self) -> None:
        """Inventing interior points would imply a distribution that is absent."""
        assert lorenz_curve([]) == [(0.0, 0.0), (1.0, 1.0)]
        assert lorenz_curve([0, 0]) == [(0.0, 0.0), (1.0, 1.0)]

    def test_negative_values_are_rejected(self) -> None:
        """Undefined, same as the coefficient."""
        with pytest.raises(ValueError, match="negative"):
            lorenz_curve([5, -2])
