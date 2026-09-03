# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The report is rendered under two themes, so no colour may be baked in.

Every chart specification is written once and displayed under both the
light and the dark theme. A theme-dependent colour placed in the Python
layout can therefore only ever be right under one of them.

It was wrong for both. The shared base layout and two builders each set
the light theme's grid and line colours, and the client-side manager's
attempt to override them was written as dotted attribute strings --
``'xaxis.gridcolor'`` -- a form Plotly expands in ``relayout`` but not in
``newPlot``. The first paint of every chart therefore kept a light grid
and Plotly's default ``#444`` text. Under the dark theme that is 1.78:1
against the plot area, where WCAG 2.1 AA requires 4.5:1.

These tests assert the two properties that failure needed: that no theme
colour survives serialisation, and that the manager's overrides are in a
form ``newPlot`` reads.
"""

from __future__ import annotations

import datetime
import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from reveille.adapters import renderer as renderer_module
from reveille.domain.models import (
    Commit,
    ContributorStats,
    FileStats,
    RankedContributor,
)
from reveille.domain.profile import AXIS_ORDER, ProfileAxis

_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "src" / "reveille" / "templates" / "report.html.j2"
)

_COLOUR_KEYS = frozenset(
    {
        "paper_bgcolor",
        "plot_bgcolor",
        "gridcolor",
        "linecolor",
        "zerolinecolor",
        "tickcolor",
        "bgcolor",
        "bordercolor",
        "activecolor",
    }
)


def _relative_luminance(hex_colour: str) -> float:
    """Return the WCAG relative luminance of a ``#rrggbb`` colour."""
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG 2.1 contrast ratio between two ``#rrggbb`` colours."""
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _theme_layouts() -> dict[str, dict[str, Any]]:
    """Parse ``THEME_LAYOUTS`` out of the template as real data.

    The block is read from the shipped template rather than restated
    here, so the test cannot drift away from what the report carries.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")
    start = text.index("var THEME_LAYOUTS = {")
    body = text[start + len("var THEME_LAYOUTS = ") :]

    depth = 0
    for index, character in enumerate(body):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                literal = body[: index + 1]
                break
    else:  # pragma: no cover - unbalanced braces would fail earlier
        pytest.fail("THEME_LAYOUTS object literal is unbalanced")

    literal = re.sub(r"//[^\n]*", "", literal)
    literal = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', literal)
    literal = literal.replace("'", '"')
    literal = re.sub(r",(\s*[}\]])", r"\1", literal)
    return json.loads(literal)


def _walk(node: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    """Yield every ``(path, value)`` leaf of a nested mapping."""
    found: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_walk(value, (*path, str(key))))
    else:
        found.append((path, node))
    return found


class TestThemeOverridesAreInAFormPlotlyReads:
    """`newPlot` takes a layout object. It does not expand dotted keys."""

    def test_no_override_key_contains_a_dot(self) -> None:
        dotted = [
            "/".join(path)
            for theme in _theme_layouts().values()
            for path, _ in _walk(theme)
            if any("." in segment for segment in path)
        ]
        assert dotted == [], (
            "dotted attribute strings are silently ignored by Plotly.newPlot "
            f"and react, so these overrides would never apply: {dotted}"
        )

    def test_both_themes_define_the_same_overrides(self) -> None:
        """A key present in one theme and absent in the other cannot switch."""
        layouts = _theme_layouts()
        light = {path for path, _ in _walk(layouts["light"])}
        dark = {path for path, _ in _walk(layouts["dark"])}
        assert light == dark, (
            "a colour defined under one theme only keeps the other theme's "
            f"value when switched: {sorted(light ^ dark)}"
        )

    def test_every_override_is_a_colour_the_document_also_defines(self) -> None:
        """Chart colours must come from the same tokens as the page."""
        css = _TEMPLATE.read_text(encoding="utf-8")
        for theme, layout in _theme_layouts().items():
            for path, value in _walk(layout):
                if not isinstance(value, str) or not value.startswith("#"):
                    continue
                assert value.lower() in css.lower(), (
                    f"{theme} {'.'.join(path)} = {value} appears nowhere else "
                    "in the document; chart and page would drift apart"
                )


class TestChartTextMeetsContrastUnderBothThemes:
    """WCAG 2.1 AA: 4.5:1 for body text, 3:1 for graphical objects."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_axis_text_against_the_plot_area(self, theme: str) -> None:
        layout = _theme_layouts()[theme]
        ratio = contrast_ratio(layout["font"]["color"], layout["plot_bgcolor"])
        assert ratio >= 4.5, (
            f"{theme}: axis and legend text is {ratio:.2f}:1 against the plot "
            "area, below the 4.5:1 that WCAG 2.1 AA requires"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_axis_text_against_the_paper(self, theme: str) -> None:
        layout = _theme_layouts()[theme]
        ratio = contrast_ratio(layout["font"]["color"], layout["paper_bgcolor"])
        assert ratio >= 4.5, f"{theme}: text is {ratio:.2f}:1 against the paper"

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_the_grid_is_visible_but_recessive(self, theme: str) -> None:
        """A grid must be findable without competing with the data.

        The dark theme once painted the light theme's `#e2e8f0` grid over
        a `#161b22` plot: 14.03:1, louder than the series drawn on it.
        """
        layout = _theme_layouts()[theme]
        ratio = contrast_ratio(layout["xaxis"]["gridcolor"], layout["plot_bgcolor"])
        assert 1.1 <= ratio <= 3.0, (
            f"{theme}: the grid is {ratio:.2f}:1 against the plot area; "
            "outside 1.1-3.0 it is either invisible or louder than the data"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_toolbar_icons_are_legible_at_rest_and_on_hover(self, theme: str) -> None:
        """The camera and zoom icons, in both of their states.

        Left unset, Plotly derives these from `paper_bgcolor`: the icon is
        drawn at 30% of a contrast colour and repainted at 70% on hover.
        Both ends are pinned so neither state depends on a background the
        theme manager changes underneath it.
        """
        modebar = _theme_layouts()[theme]["modebar"]
        rest = contrast_ratio(modebar["color"], modebar["bgcolor"])
        hover = contrast_ratio(modebar["activecolor"], modebar["bgcolor"])
        assert rest >= 3.0, f"{theme}: toolbar icon is {rest:.2f}:1 at rest"
        assert hover >= 3.0, f"{theme}: toolbar icon is {hover:.2f}:1 on hover"
        assert hover > rest, (
            f"{theme}: hovering takes the icon from {rest:.2f}:1 to "
            f"{hover:.2f}:1, so it does not read as a response to the pointer"
        )


class TestNoChartSpecificationCarriesAThemeColour:
    """The property the two bad builders and the base layout each broke.

    Asserted over every builder rather than the three that were wrong,
    because the next builder is the one that matters.
    """

    def test_every_builder_emits_a_colourless_layout(self) -> None:
        commits = [
            _commit(datetime.datetime(2024, 1, 1 + day, tzinfo=datetime.UTC)) for day in range(10)
        ]
        ranked = [
            RankedContributor(
                stats=ContributorStats(
                    name=f"Dev {i}",
                    email=f"dev{i}@example.com",
                    commit_count=10 - i,
                    lines_added=100,
                    lines_deleted=10,
                    active_days=5,
                    first_commit_date=datetime.date(2024, 1, 1),
                    last_commit_date=datetime.date(2024, 6, 1),
                ),
                composite_score=float(10 - i),
                percentile=50.0,
                tier=1,
                tier_designation="Private",
            )
            for i in range(4)
        ]

        profile_axes = [ProfileAxis(name, 0.5, "d") for name in AXIS_ORDER]

        files = [
            FileStats(
                path=f"src/module_{index}.py",
                commits=index + 1,
                lines_added=100 - index,
                lines_deleted=index,
            )
            for index in range(5)
        ]

        builders = [
            (name, function)
            for name, function in vars(renderer_module).items()
            if name.startswith("_build_") and inspect.isfunction(function)
        ]
        assert builders, "no chart builders were found to check"

        offences: list[str] = []
        checked = 0
        for name, function in builders:
            parameter = next(iter(inspect.signature(function).parameters), None)
            if parameter is None:
                continue
            if "axes" in parameter:
                argument = profile_axes
            elif "file" in parameter:
                argument = files
            elif "commit" in parameter:
                argument = commits
            else:
                argument = ranked
            try:
                emitted = function(argument)
            except TypeError:
                continue
            if not isinstance(emitted, str) or emitted == "null":
                continue
            checked += 1
            layout = json.loads(emitted).get("layout", {})
            offences.extend(
                f"{name}: {'.'.join(path)} = {value}"
                for path, value in _walk(layout)
                if path and path[-1] in _COLOUR_KEYS
            )

        assert checked >= 7, f"only {checked} builders produced a figure to check"
        assert offences == [], (
            "a chart specification is displayed under both themes, so a "
            f"colour baked into one can only be right under one: {offences}"
        )


def _commit(when: datetime.datetime) -> Commit:
    """A commit carrying only the fields the chart builders read."""
    return Commit(
        sha="0" * 40,
        author_name="Dev 0",
        author_email="dev0@example.com",
        timestamp=when,
        lines_added=10,
        lines_deleted=1,
    )
