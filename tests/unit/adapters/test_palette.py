# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The chart palette, recomputed rather than trusted.

Colour carries meaning here: a hue is an identity. Two series drawn in
colours a reader cannot separate state something false, and the previous
eight-slot palette did exactly that -- 13 of its 28 pairs fell below the
target, and three pairs were indistinguishable in *normal* vision:
orange against red at 7.1, magenta against red at 7.8, blue against
violet at 9.8.

Colour is also the one thing a hand check cannot do. These tests carry
the arithmetic -- OKLab distance, the Vienot-Brettel-Mollon dichromat
simulation, and the WCAG contrast ratio -- so the constraints are
measured on every run.
"""

from __future__ import annotations

import itertools

import pytest

from reveille.adapters.renderer import (
    _CATEGORICAL_PALETTE,
    _EQUALITY_LINE_COLOUR,
    _LINES_ADDED_COLOUR,
    _LINES_DELETED_COLOUR,
    _MAX_SERIES,
    _OTHER_SLICE_COLOUR,
    _PIE_MAX_SLICES,
)

#: The two plot surfaces a series is drawn on. One palette serves both,
#: because the theme toggle changes the surface and not the series.
_LIGHT_SURFACE = "#f6f8fa"
_DARK_SURFACE = "#161b22"

#: Below this, two series are indistinguishable to a normal-vision reader.
_NORMAL_VISION_FLOOR = 15.0

#: Dichromat floor. Admissible only with secondary encoding, which this
#: report has: every chart using the palette carries a legend, the pies
#: carry direct labels, and the contributor table restates every figure.
_DICHROMAT_FLOOR = 6.0

#: WCAG 2.1 minimum for a graphical object that conveys information.
_GRAPHICAL_CONTRAST = 3.0


def _to_linear(value: float) -> float:
    """Convert one sRGB channel to linear light."""
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_rgb(colour: str) -> list[float]:
    """Return a `#rrggbb` colour as linear-light RGB."""
    return [_to_linear(int(colour[i : i + 2], 16) / 255) for i in (1, 3, 5)]


def _multiply(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Multiply a 3x3 matrix by a 3-vector."""
    return [sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3)]


# Hunt-Pointer-Estevez cone fundamentals, D65 normalised.
_RGB_TO_LMS = [
    [0.31399022, 0.63951294, 0.04649755],
    [0.15537241, 0.75789446, 0.08670142],
    [0.01775239, 0.10944209, 0.87256922],
]
_LMS_TO_RGB = [
    [5.47221206, -4.64196010, 0.16963708],
    [-1.12524190, 2.29317094, -0.16789520],
    [0.02980165, -0.19318073, 1.16364789],
]

#: Vienot, Brettel & Mollon (1999) dichromat projections.
_DICHROMAT = {
    "protanopia": [[0, 1.05118294, -0.05116099], [0, 1, 0], [0, 0, 1]],
    "deuteranopia": [[1, 0, 0], [0.9513092, 0, 0.04866992], [0, 0, 1]],
    "tritanopia": [[1, 0, 0], [0, 1, 0], [-0.86744736, 1.86727089, 0]],
}


def _simulate(colour: str, deficiency: str) -> list[float]:
    """Return a colour as a dichromat sees it, in linear RGB."""
    cones = _multiply(_RGB_TO_LMS, _linear_rgb(colour))
    return _multiply(_LMS_TO_RGB, _multiply(_DICHROMAT[deficiency], cones))


def _oklab(rgb: list[float]) -> tuple[float, float, float]:
    """Convert linear RGB to OKLab, where Euclidean distance is perceptual."""
    red, green, blue = (max(0.0, min(1.0, channel)) for channel in rgb)
    long_ = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    l_, m_, s_ = (value ** (1 / 3) if value > 0 else 0.0 for value in (long_, medium, short))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def perceptual_distance(first: str, second: str, deficiency: str | None = None) -> float:
    """Return the OKLab distance between two colours, optionally as a dichromat sees them."""
    left = _simulate(first, deficiency) if deficiency else _linear_rgb(first)
    right = _simulate(second, deficiency) if deficiency else _linear_rgb(second)
    a, b = _oklab(left), _oklab(right)
    return 100 * sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def chroma(colour: str) -> float:
    """Return a colour's OKLab chroma: 0 is grey, higher is more saturated."""
    _, a, b = _oklab(_linear_rgb(colour))
    return 100 * (a * a + b * b) ** 0.5


def contrast_ratio(first: str, second: str) -> float:
    """Return the WCAG 2.1 contrast ratio between two colours."""

    def luminance(colour: str) -> float:
        r, g, b = _linear_rgb(colour)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


_PAIRS = list(itertools.combinations(_CATEGORICAL_PALETTE, 2))


@pytest.mark.unit
class TestTheSimulationItselfIsRight:
    """A CVD check that cannot see a known-confusable pair proves nothing."""

    def test_red_and_green_collapse_under_deuteranopia(self) -> None:
        separated = perceptual_distance("#008300", "#e66767")
        confused = perceptual_distance("#008300", "#e66767", "deuteranopia")
        assert separated > 30, "the reference pair should be far apart normally"
        assert confused < separated / 1.5, (
            "the deuteranopia simulation did not narrow a red/green pair, so "
            "it is not simulating anything"
        )

    def test_black_and_white_stay_apart_under_every_deficiency(self) -> None:
        """Dichromacy costs hue, not lightness."""
        for deficiency in _DICHROMAT:
            assert perceptual_distance("#000000", "#ffffff", deficiency) > 90


@pytest.mark.unit
class TestEverySeriesPairIsDistinguishable:
    """One hue per identity. Two identities may not share an appearance."""

    @pytest.mark.parametrize(("first", "second"), _PAIRS)
    def test_normal_vision_separation(self, first: str, second: str) -> None:
        distance = perceptual_distance(first, second)
        assert distance >= _NORMAL_VISION_FLOOR, (
            f"{first} and {second} are {distance:.1f} apart in normal vision; "
            f"below {_NORMAL_VISION_FLOOR} no reader can separate them, and "
            "secondary encoding does not excuse this one"
        )

    @pytest.mark.parametrize(("first", "second"), _PAIRS)
    @pytest.mark.parametrize("deficiency", sorted(_DICHROMAT))
    def test_dichromat_separation(self, first: str, second: str, deficiency: str) -> None:
        distance = perceptual_distance(first, second, deficiency)
        assert distance >= _DICHROMAT_FLOOR, (
            f"{first} and {second} are {distance:.1f} apart under {deficiency}"
        )


@pytest.mark.unit
class TestEverySeriesIsLegibleOnBothSurfaces:
    """The theme toggle changes the surface. It does not change the series."""

    @pytest.mark.parametrize("colour", _CATEGORICAL_PALETTE)
    @pytest.mark.parametrize(
        ("surface", "theme"), [(_LIGHT_SURFACE, "light"), (_DARK_SURFACE, "dark")]
    )
    def test_series_contrast(self, colour: str, surface: str, theme: str) -> None:
        ratio = contrast_ratio(colour, surface)
        assert ratio >= _GRAPHICAL_CONTRAST, (
            f"{colour} is {ratio:.2f}:1 on the {theme} plot surface, below the "
            f"{_GRAPHICAL_CONTRAST}:1 WCAG 2.1 requires of a graphical object"
        )

    @pytest.mark.parametrize(
        "colour", [_LINES_ADDED_COLOUR, _LINES_DELETED_COLOUR, _OTHER_SLICE_COLOUR]
    )
    @pytest.mark.parametrize("surface", [_LIGHT_SURFACE, _DARK_SURFACE])
    def test_named_colours_are_held_to_the_same_bar(self, colour: str, surface: str) -> None:
        assert contrast_ratio(colour, surface) >= _GRAPHICAL_CONTRAST


@pytest.mark.unit
class TestTheNonSeriesColoursReadAsScaffolding:
    """A reference line and a residual are not identities and must not look like one."""

    @pytest.mark.parametrize("colour", [_OTHER_SLICE_COLOUR, _EQUALITY_LINE_COLOUR])
    def test_they_are_not_in_the_series_palette(self, colour: str) -> None:
        assert colour not in _CATEGORICAL_PALETTE

    @pytest.mark.parametrize("colour", [_OTHER_SLICE_COLOUR, _EQUALITY_LINE_COLOUR])
    def test_they_are_achromatic(self, colour: str) -> None:
        """Saturation, not hue distance, is what separates these two roles.

        A grey cannot be 15 OKLab units from four saturated hues *and*
        clear 3:1 on both surfaces -- it sits mid-lightness, so it is
        always near something. That is the wrong test regardless. What
        makes a residual read as scaffolding is that it carries no hue
        while every identity does.
        """
        assert chroma(colour) < 2.0, (
            f"{colour} has chroma {chroma(colour):.1f}; a residual or a "
            "reference line that carries a hue reads as another series"
        )

    @pytest.mark.parametrize("series", _CATEGORICAL_PALETTE)
    def test_every_identity_carries_a_hue(self, series: str) -> None:
        assert chroma(series) > 8.0, (
            f"{series} has chroma {chroma(series):.1f}, close enough to grey "
            "to be mistaken for the aggregate slice or the reference line"
        )

    @pytest.mark.parametrize("series", _CATEGORICAL_PALETTE)
    def test_the_residual_is_still_visibly_apart(self, series: str) -> None:
        """In a pie every slice is visible at once, so this is the strict case."""
        distance = perceptual_distance(_OTHER_SLICE_COLOUR, series)
        assert distance >= 8.0, (
            f"the residual slice is {distance:.1f} from {series}; a reader "
            "would take the aggregate for a person"
        )


@pytest.mark.unit
class TestTheCapsFollowThePalette:
    """Anything beyond the palette aggregates. It never reuses a hue."""

    def test_series_cap_equals_the_palette_length(self) -> None:
        assert len(_CATEGORICAL_PALETTE) == _MAX_SERIES

    def test_pie_slice_cap_equals_the_palette_length(self) -> None:
        assert len(_CATEGORICAL_PALETTE) == _PIE_MAX_SLICES
