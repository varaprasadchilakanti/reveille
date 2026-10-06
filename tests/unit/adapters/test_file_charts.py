# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The two file-level charts, and the reader that feeds them.

`git log --numstat` was already carrying a path on every line and the
totals were being summed out of a structure that had them. These charts
therefore cost no extra Git work -- only the parsing already paid for --
which is the reason they can exist without touching the read that 0.7.0
made 9.4x faster.
"""

from __future__ import annotations

import datetime
import json
import math
import re
from pathlib import Path

import pytest

from reveille.adapters.git_reader import _iter_numstat, _rename_destination
from reveille.adapters.renderer import _build_extension_chart, _build_hotspot_chart
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    Commit,
    FileStats,
    ReportData,
    RepositoryMetadata,
)

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


def _file(path: str, commits: int = 1, added: int = 0, deleted: int = 0) -> FileStats:
    return FileStats(path=path, commits=commits, lines_added=added, lines_deleted=deleted)


@pytest.mark.unit
class TestNumstatParsing:
    """The paths were being discarded, not absent."""

    def test_a_plain_line_yields_path_and_counts(self) -> None:
        assert list(_iter_numstat("10\t2\tsrc/a.py")) == [("src/a.py", 10, 2)]

    def test_a_binary_file_contributes_zero(self) -> None:
        assert list(_iter_numstat("-\t-\tlogo.png")) == [("logo.png", 0, 0)]

    def test_a_short_line_is_skipped(self) -> None:
        assert list(_iter_numstat("garbage")) == []

    def test_an_empty_block_yields_nothing(self) -> None:
        assert list(_iter_numstat("")) == []

    def test_a_path_containing_spaces_survives(self) -> None:
        assert list(_iter_numstat("1\t0\tdocs/my file.md")) == [("docs/my file.md", 1, 0)]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("a.py", "a.py"),
            ("old.py => new.py", "new.py"),
            ("src/{old => new}/f.py", "src/new/f.py"),
            ("src/a/{x.py => y.py}", "src/a/y.py"),
        ],
    )
    def test_a_rename_resolves_to_its_destination(self, raw: str, expected: str) -> None:
        """Counting both sides doubles a file; counting the source attributes
        churn to a path that no longer exists."""
        assert _rename_destination(raw) == expected


@pytest.mark.unit
class TestTheHotspotChart:
    def test_empty_input_produces_no_chart(self) -> None:
        assert _build_hotspot_chart([]) == "null"

    def test_only_generated_files_produces_no_chart(self) -> None:
        """Excluding every candidate must not draw an empty axis."""
        assert _build_hotspot_chart([_file("poetry.lock", added=999)]) == "null"

    def test_the_highest_churn_is_drawn_last_so_it_reads_at_the_top(self) -> None:
        files = [_file("small.py", added=1), _file("big.py", added=900)]
        trace = json.loads(_build_hotspot_chart(files))["data"][0]
        assert trace["y"][-1] == "big.py"

    def test_the_hover_reports_commits_as_well_as_churn(self) -> None:
        trace = json.loads(_build_hotspot_chart([_file("a.py", commits=7, added=9)]))["data"][0]
        assert trace["customdata"] == [7]
        assert "Commits" in trace["hovertemplate"]

    def test_no_contributor_is_named(self) -> None:
        emitted = _build_hotspot_chart([_file("a.py", added=10)])
        assert "@" not in emitted


@pytest.mark.unit
class TestTheExtensionChart:
    def test_empty_input_produces_no_chart(self) -> None:
        assert _build_extension_chart([]) == "null"

    def test_totals_are_preserved(self) -> None:
        files = [_file(f"f{i}.e{i}", added=10) for i in range(20)]
        trace = json.loads(_build_extension_chart(files))["data"][0]
        assert sum(trace["y"]) == 200

    def test_it_uses_a_palette_colour_rather_than_a_literal(self) -> None:
        from reveille.adapters.renderer import _CATEGORICAL_PALETTE

        trace = json.loads(_build_extension_chart([_file("a.py", added=1)]))["data"][0]
        assert trace["marker"]["color"] in _CATEGORICAL_PALETTE


@pytest.mark.unit
class TestBothAreWiredIntoTheReport:
    """A builder nothing renders is dead code."""

    @pytest.mark.parametrize("chart", ["hotspots", "extensions"])
    def test_the_template_embeds_and_draws_it(self, chart: str) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert f'id="spec-{chart}"' in template
        assert f"charts.{chart} | safe" in template, (
            "without `| safe` the specification is HTML-escaped and never parses"
        )
        assert f'id="chart-{chart}"' in template
        assert f"'{chart}'" in template, "the client script never initialises it"

    def test_the_reader_exposes_file_stats(self) -> None:
        """The service reads this attribute; it must exist before any call."""
        from reveille.adapters.git_reader import GitReader

        reader = GitReader(Path(__file__).resolve().parents[3])
        assert reader.file_stats == ()

    def test_report_data_carries_them(self) -> None:
        from reveille.domain.models import ReportData

        assert "file_stats" in ReportData.__dataclass_fields__


_PROFILE_SINCE = datetime.date(2024, 1, 1)
_PROFILE_UNTIL = datetime.date(2024, 6, 1)


def _report_data() -> ReportData:
    """A report with enough history for all three profile measures to move."""
    span = (_PROFILE_UNTIL - _PROFILE_SINCE).days
    commits = [
        Commit(
            sha=f"{day:040d}",
            author_name="Dev",
            author_email="dev@example.com",
            timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
            + datetime.timedelta(days=day),
            lines_added=12,
            lines_deleted=3,
        )
        for day in range(0, span, 5)
    ]
    files = [
        FileStats(path=f"src/f{i}.py", commits=2 if i % 3 else 1, lines_added=9, lines_deleted=1)
        for i in range(9)
    ]
    return ReportData(
        metadata=RepositoryMetadata(
            name="test-repo",
            remote_url=None,
            analysed_branch="main",
            total_commits=len(commits),
            unique_contributors=1,
            analysis_since=_PROFILE_SINCE,
            analysis_until=_PROFILE_UNTIL,
            generated_at=datetime.datetime(2024, 6, 2, 12, 0, tzinfo=datetime.UTC),
        ),
        provenance=AnalysisProvenance(
            reveille_version="0.0.0-test",
            schema_version=SCHEMA_VERSION,
            head_sha="0" * 40,
            requested_branch=None,
            requested_since=None,
            requested_until=None,
            exclude_authors_count=0,
            min_commits=1,
            ranking_enabled=False,
            ranking_weights=None,
            mailmap_applied=False,
            deterministic=False,
        ),
        ranked_contributors=[],
        commits=commits,
        file_stats=files,
    )


@pytest.mark.unit
class TestTheRepositoryProfileSection:
    """The profile is a table with bars in it, not a chart. ADR 0012.

    It was a Plotly radar until 0.9.0. Area is read far less accurately than
    length from a common baseline (Cleveland & McGill, JASA 1984), the
    enclosed area depended on an axis order that carries no meaning, and the
    report told the reader "read it as five numbers, not as a shape" -- an
    admission that the form was wrong rather than a mitigation of it.

    These assert the three things the change was for: the figures are in the
    HTML rather than in a chart specification, so they survive JavaScript
    being off; they are visible, where the radar's numbers lived only in a
    visually-hidden table; and each expectation is shown only where one can
    be computed.
    """

    @staticmethod
    def _rendered(tmp_path: Path) -> str:
        from reveille.adapters.renderer import Renderer

        out = tmp_path / "report.html"
        Renderer().render(_report_data(), out)
        return out.read_text(encoding="utf-8")

    def test_the_figures_are_in_the_markup_not_in_a_chart_specification(
        self, tmp_path: Path
    ) -> None:
        """With JavaScript off the radar drew nothing at all."""
        html = self._rendered(tmp_path)
        assert 'id="spec-profile"' not in html, "the profile is no longer a Plotly chart"
        assert 'id="chart-profile"' not in html
        body = html[html.index("Repository Profile") :]
        assert "profile-value" in body[: body.index("</table>")]

    def test_one_row_per_axis(self, tmp_path: Path) -> None:
        from reveille.domain.profile import AXIS_ORDER

        html = self._rendered(tmp_path)
        table = html[
            html.index('<table class="profile">') : html.index(
                "</table>", html.index('<table class="profile">')
            )
        ]
        assert table.count("<tr>") == len(AXIS_ORDER) + 1, (
            "expected a header row and one row per axis"
        )
        for name in AXIS_ORDER:
            assert name in table, f"{name} is missing from the profile table"

    def test_the_bar_length_matches_the_value(self, tmp_path: Path) -> None:
        """No rescaling: a 40% share must draw a 40% bar."""
        html = self._rendered(tmp_path)
        fills = re.findall(r'class="meter-fill" style="width: ([\d.]+)%"', html)
        values = re.findall(r'class="profile-value">(\d+)%<', html)
        assert fills and len(fills) == len(values)
        for width, shown in zip(fills, values, strict=True):
            assert abs(float(width) - float(shown)) <= 1.0, (
                f"a bar of {width}% is drawn for a stated {shown}%"
            )

    def test_an_expectation_is_marked_only_where_one_can_be_computed(self, tmp_path: Path) -> None:
        """Revisiting has none; inventing one would read as a target."""
        from reveille.domain.profile import repository_profile

        html = self._rendered(tmp_path)
        data = _report_data()
        axes = repository_profile(
            data.commits,
            data.file_stats,
            data.metadata.analysis_since,
            data.metadata.analysis_until,
        )
        computable = [a for a in axes if a.expected is not None]
        assert computable, "no axis offers an expectation, so this proves nothing"
        assert len(re.findall(r'class="meter-tick"', html)) == len(computable)
        assert any(a.expected is None for a in axes), (
            "every axis has one; the absent case is untested"
        )

    def test_the_section_says_an_expectation_is_not_a_target(self, tmp_path: Path) -> None:
        """The distinction the whole design rests on."""
        html = self._rendered(tmp_path)
        foot = html[html.index("Repository Profile") :]
        assert "not a target" in foot
        assert "None of these is a goal" in foot

    def test_it_no_longer_claims_to_be_a_shape(self, tmp_path: Path) -> None:
        """The radar's caveats went with the radar."""
        html = self._rendered(tmp_path)
        assert "read it as five numbers" not in html.lower()
        assert "enclosed area" not in html.lower()


@pytest.mark.unit
class TestTheContributionBreakdownUsesOneFormPerQuestion:
    """Part-of-whole gets the pie; two series get the bar."""

    def test_the_share_pie_is_wired_and_the_duplicates_are_not(self) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert 'id="chart-pie_commits"' in template, (
            "commit share is part-of-whole, which is what a pie is for"
        )
        assert 'id="chart-contributor_lines"' in template, (
            "added against deleted is two series, which a pie cannot show"
        )
        for gone in ("chart-contributor_commits", "chart-pie_lines"):
            assert gone not in template, f"{gone} duplicated the chart beside it"

    def test_no_builder_is_left_unwired(self) -> None:
        """A builder nothing renders is dead code."""
        import inspect

        from reveille.adapters import renderer as module

        source = inspect.getsource(module.Renderer._build_charts)
        for name, function in vars(module).items():
            if not (name.startswith("_build_") and inspect.isfunction(function)):
                continue
            if name == "_build_heatmap_data":
                continue  # consumed by the client script, not a chart spec
            assert name in source, f"{name} is never called by _build_charts"


@pytest.mark.unit
class TestTheProfileFlower:
    """ADR 0016: separate petals above the table, drawn without a script."""

    def _html(self, tmp_path: Path) -> str:
        return TestTheRepositoryProfileSection()._rendered(tmp_path)

    def test_six_separate_petals_in_inline_svg(self, tmp_path: Path) -> None:
        html = self._html(tmp_path)
        flower = html[html.index('<figure class="profile-flower">') : html.index("</figure>")]

        assert flower.count('class="flower-track"') == 6
        assert "polygon" not in flower, "never joined into a shape whose area misleads"
        assert 'id="spec-profile"' not in html

    def test_the_label_carries_every_value(self, tmp_path: Path) -> None:
        html = self._html(tmp_path)
        label = re.search(r'<svg viewBox="0 0 440 440" role="img"\s+aria-label="([^"]*)"', html)

        assert label
        for name in (
            "Continuity",
            "Recent work",
            "Shared",
            "Collaboration",
            "Revisiting",
            "Automation",
        ):
            assert re.search(rf"{name} \d+%", label.group(1)), name

    def test_expectations_are_marked_where_computable(self, tmp_path: Path) -> None:
        html = self._html(tmp_path)

        assert html.count('class="flower-expected"') == html.count('class="meter-tick"')
        # On a ring of the page colour, or it falls below 3:1 against a petal.
        assert html.count('class="flower-expected-halo"') == html.count('class="flower-expected"')


def _radius(path: str) -> float:
    """The radius of a petal wedge or expectation arc, from its `A` command."""
    match = re.search(r"A ([\d.]+) ", path)
    assert match, path
    return float(match.group(1))


@pytest.mark.unit
class TestTheFlowerGeometry:
    """The petal is the figure: its length, its mark and its place are checked."""

    def _petals(self, values: list[float], expected: list[float | None]) -> list[dict]:
        from reveille.adapters.renderer import _profile_flower
        from reveille.domain.profile import AXIS_ORDER, ProfileAxis

        return _profile_flower(
            [
                ProfileAxis(name=name, value=value, description="", expected=mark)
                for name, value, mark in zip(AXIS_ORDER, values, expected, strict=True)
            ]
        )

    def test_length_is_the_share_from_centre_to_rim(self) -> None:
        petals = self._petals([1.0, 0.5, 0.25, 0.1, 0.75, 0.0], [None] * 6)

        assert [_radius(p["petal"]) for p in petals[:5]] == [120.0, 60.0, 30.0, 12.0, 90.0]
        assert petals[5]["petal"] == "", "0% draws no petal"
        assert all(_radius(p["track"]) == 120.0 for p in petals), "every track reaches the rim"

    def test_the_mark_sits_at_the_expected_value_not_the_value(self) -> None:
        petals = self._petals([0.9, 0.2, 0.5, 0.1, 0.1, 0.1], [0.5, 0.25, None, None, None, None])

        assert _radius(petals[0]["expected"]) == 60.0
        assert _radius(petals[1]["expected"]) == 30.0
        assert petals[2]["expected"] is None

    def test_the_order_runs_clockwise_from_the_top(self) -> None:
        """Continuity at twelve o'clock, then clockwise in `AXIS_ORDER`."""
        petals = self._petals([0.5] * 6, [None] * 6)
        angles = [
            math.degrees(math.atan2(float(p["label_y"]) - 220, float(p["label_x"]) - 220))
            for p in petals
        ]

        assert [round(a) for a in angles] == [-90, -30, 30, 90, 150, -150]

    def test_colours_come_from_the_theme(self) -> None:
        from reveille.adapters import renderer

        template = (
            Path(renderer.__file__).parent.parent / "templates" / "report.html.j2"
        ).read_text(encoding="utf-8")
        rules = re.findall(r"\.flower-[\w-]+\s*\{([^}]*)\}", template)

        assert len(rules) >= 6
        for rule in rules:
            assert "#" not in rule, f"a fixed colour cannot follow dark mode: {rule.strip()}"
            for colour in re.findall(r"(?:fill|stroke):\s*([^;]+);", rule):
                assert colour.startswith("var(--color-") or colour == "none", colour
