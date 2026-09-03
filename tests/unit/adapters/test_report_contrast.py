"""Colour contrast tests for the report template.

The report is distributed to stakeholders — embedded in Confluence, sent
by email — which is the context where accessibility is asked about. Both
themes must meet WCAG 2.1 AA for text.

Contrast is computed from the CSS custom properties declared in the
template rather than asserted against a copy of them, so a token edited
in the template is checked here without anyone remembering to update a
fixture. The muted token failed AA in both themes until v0.7.0.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import reveille

_TEMPLATE = Path(reveille.__file__).parent / "templates" / "report.html.j2"

# WCAG 2.1 SC 1.4.3 (Contrast Minimum), AA, normal-size text.
_AA_NORMAL_TEXT = 4.5


def _relative_luminance(hex_colour: str) -> float:
    """Compute relative luminance per WCAG 2.1 definition.

    Args:
        hex_colour: A colour in `#rrggbb` form.

    Returns:
        Relative luminance in the range [0, 1].
    """
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    """Compute the WCAG contrast ratio between two colours.

    Args:
        foreground: Text colour in `#rrggbb` form.
        background: Background colour in `#rrggbb` form.

    Returns:
        The ratio, between 1.0 (identical) and 21.0 (black on white).
    """
    a, b = _relative_luminance(foreground), _relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def _tokens_for(theme: str) -> dict[str, str]:
    """Extract the CSS custom properties declared for one theme.

    Args:
        theme: Either "light" or "dark".

    Returns:
        A mapping of custom-property name to `#rrggbb` value.
    """
    source = _TEMPLATE.read_text(encoding="utf-8")
    selector = r":root\s*\{" if theme == "light" else r'\[data-theme="dark"\]\s*\{'
    match = re.search(selector + r"(.*?)\}", source, re.DOTALL)
    assert match is not None, f"no {theme} theme block found in the template"
    return dict(re.findall(r"(--color-[\w-]+):\s*(#[0-9a-fA-F]{6});", match.group(1)))


# Every foreground token that renders text, against both surfaces it can sit on.
_TEXT_TOKENS = ["--color-text-primary", "--color-text-secondary", "--color-text-muted"]
# Every surface token the template declares, derived rather than listed.
# It was previously ["--color-bg", "--color-surface"], omitting
# --color-surface-raised. In the light theme that is #ffffff, identical to
# --color-bg, so nothing looked wrong; in the dark theme it is a distinct
# third surface, and muted text on it measured 4.08:1 -- below AA, on the
# title of every chart, on every finding's evidence figure, and on every
# empty state. A guard that lists its inputs stops covering the ones added
# after it was written.
_BACKGROUNDS = ["--color-bg", "--color-surface", "--color-surface-raised"]


@pytest.mark.unit
class TestThemeContrast:
    """Tests for WCAG AA text contrast in both report themes."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("foreground", _TEXT_TOKENS)
    @pytest.mark.parametrize("background", _BACKGROUNDS)
    def test_text_meets_aa_contrast(self, theme: str, foreground: str, background: str) -> None:
        tokens = _tokens_for(theme)
        ratio = _contrast_ratio(tokens[foreground], tokens[background])
        assert ratio >= _AA_NORMAL_TEXT, (
            f"{theme}: {foreground} ({tokens[foreground]}) on {background} "
            f"({tokens[background]}) is {ratio:.2f}:1, below AA {_AA_NORMAL_TEXT}:1"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_muted_stays_visually_below_secondary(self, theme: str) -> None:
        """Raising contrast must not flatten the visual hierarchy.

        Muted text exists to recede. If a contrast fix pushed it to the
        same weight as secondary text, the fix would have destroyed the
        distinction it was meant to preserve.
        """
        tokens = _tokens_for(theme)
        background = tokens["--color-surface"]
        muted = _contrast_ratio(tokens["--color-text-muted"], background)
        secondary = _contrast_ratio(tokens["--color-text-secondary"], background)
        assert muted < secondary
