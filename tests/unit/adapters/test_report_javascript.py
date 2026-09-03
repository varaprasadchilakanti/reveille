# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The report's inline JavaScript, executed rather than read.

`mergeLayout` is what makes the nested theme overrides safe. The shallow
`Object.assign` it replaced would have taken an axis title with it the
moment a themed `xaxis` was applied, and nothing in a Python test suite
would have noticed.

The function is extracted from the shipped template and run under Node,
so the code under test is the code the report carries. Node ships on the
CI runner; where it is absent these skip, and the report is still covered
by the structural assertions in `test_report_theming.py`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "src" / "reveille" / "templates" / "report.html.j2"
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node is required to execute the report's inline JavaScript",
)


def _merge_layout_source() -> str:
    """Return the `mergeLayout` definition as it is shipped."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    start = text.index("function mergeLayout(")
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("mergeLayout is unbalanced in the template")


def merge(base: object, overlay: object) -> object:
    """Run the shipped `mergeLayout` under Node and return its result."""
    script = (
        _merge_layout_source()
        + "\nconst base = "
        + json.dumps(base)
        + ";\nconst overlay = "
        + json.dumps(overlay)
        + ";\nconst out = mergeLayout(base, overlay);"
        # Printing the base as well proves the inputs were not mutated.
        + "\nconsole.log(JSON.stringify({out: out, base: base}));"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.unit
class TestMergeLayoutKeepsWhatTheThemeDoesNotName:
    """The defect a shallow merge would reintroduce."""

    def test_an_axis_title_survives_a_themed_axis(self) -> None:
        result = merge(
            {"xaxis": {"type": "category", "tickangle": -45, "title": {"text": "Week"}}},
            {"xaxis": {"gridcolor": "#30363d"}},
        )
        axis = result["out"]["xaxis"]
        assert axis["title"] == {"text": "Week"}, (
            "a shallow merge replaces the axis wholesale and the title goes "
            "with it -- the failure this function exists to prevent"
        )
        assert axis["type"] == "category"
        assert axis["tickangle"] == -45
        assert axis["gridcolor"] == "#30363d"

    def test_nested_font_colour_does_not_erase_the_family(self) -> None:
        result = merge(
            {"font": {"family": "Inter", "size": 12}},
            {"font": {"color": "#e6edf3"}},
        )
        assert result["out"]["font"] == {
            "family": "Inter",
            "size": 12,
            "color": "#e6edf3",
        }

    def test_the_overlay_wins_on_a_shared_key(self) -> None:
        result = merge({"paper_bgcolor": "#ffffff"}, {"paper_bgcolor": "#21262d"})
        assert result["out"]["paper_bgcolor"] == "#21262d"

    def test_a_key_only_the_overlay_has_is_added(self) -> None:
        result = merge({}, {"modebar": {"color": "#8b949e"}})
        assert result["out"]["modebar"] == {"color": "#8b949e"}

    def test_a_key_only_the_base_has_is_kept(self) -> None:
        result = merge({"height": 280}, {"paper_bgcolor": "#21262d"})
        assert result["out"]["height"] == 280

    def test_arrays_are_replaced_not_merged(self) -> None:
        """A colourscale is a list of stops; merging two would corrupt it."""
        result = merge(
            {"colorscale": [[0, "#000000"], [1, "#ffffff"]]},
            {"colorscale": [[0, "#111111"]]},
        )
        assert result["out"]["colorscale"] == [[0, "#111111"]]


@pytest.mark.unit
class TestMergeLayoutDoesNotMutateItsInputs:
    """The chart specification is merged once per theme switch.

    A merge that wrote into the parsed specification would accumulate the
    previous theme's colours, so the second switch would not be a switch.
    """

    def test_the_base_is_left_alone(self) -> None:
        result = merge(
            {"xaxis": {"title": {"text": "Week"}}},
            {"xaxis": {"gridcolor": "#30363d"}},
        )
        assert result["base"] == {"xaxis": {"title": {"text": "Week"}}}, (
            "mergeLayout wrote into the chart specification; switching theme "
            "twice would carry the first theme's colours into the second"
        )

    def test_switching_back_and_forth_is_stable(self) -> None:
        spec = {"xaxis": {"title": {"text": "Week"}}}
        dark = {"xaxis": {"gridcolor": "#30363d"}}
        light = {"xaxis": {"gridcolor": "#e2e8f0"}}
        first = merge(spec, dark)["out"]
        assert first["xaxis"]["gridcolor"] == "#30363d"
        back = merge(spec, light)["out"]
        assert back["xaxis"]["gridcolor"] == "#e2e8f0"
        assert back["xaxis"]["title"] == {"text": "Week"}
