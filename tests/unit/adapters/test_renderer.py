"""Unit tests for reveille.adapters.renderer module-level functions.

The Renderer class itself is covered by the e2e test suite.
These tests exercise chart construction, derived metric helpers,
and serialisation utilities directly. All chart builders now return
Plotly JSON specification strings (or the sentinel string 'null')
rather than HTML fragments. Tests verify JSON validity, structural
completeness, and the behavioural contract for edge cases.
"""

from __future__ import annotations

import csv
import datetime
import json
from pathlib import Path
from typing import ClassVar

import plotly.graph_objects as go
import pytest

from reveille.adapters.renderer import (
    _PIE_MAX_SLICES,
    Renderer,
    _aggregate_pie_data,
    _build_commit_share_pie,
    _build_contributor_commits_chart,
    _build_contributor_lines_chart,
    _build_contributor_timeline_chart,
    _build_heatmap_data,
    _build_lines_share_pie,
    _build_timeline_chart,
    _compute_commit_concentration,
    _compute_longest_inactive_streak,
    _sanitise_chart_label,
    _to_json,
)
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    Commit,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)
from reveille.exceptions import OutputPathError

# ------------------------------------------------------------------
# Shared factory helpers
# ------------------------------------------------------------------


# Provenance is required by ReportData; these tests do not assert on it.
_PROVENANCE = AnalysisProvenance(
    reveille_version="0.0.0-test",
    schema_version=SCHEMA_VERSION,
    head_sha="0" * 40,
    requested_branch=None,
    requested_since=None,
    requested_until=None,
    exclude_authors_count=0,
    min_commits=1,
    ranking_enabled=True,
    ranking_weights={"commits": 0.3, "lines": 0.25, "consistency": 0.25, "recency": 0.2},
    mailmap_applied=False,
    deterministic=False,
)


def _make_commit(
    date: datetime.date,
    email: str = "a@example.com",
    lines_added: int = 10,
    lines_deleted: int = 2,
) -> Commit:
    return Commit(
        sha=f"{email[:3]}{date.isoformat()}",
        author_name="Author",
        author_email=email,
        timestamp=datetime.datetime(
            date.year,
            date.month,
            date.day,
            12,
            0,
            tzinfo=datetime.UTC,
        ),
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )


def _make_ranked(
    name: str,
    commit_count: int,
    lines_added: int = 200,
    lines_deleted: int = 50,
    tier: int = 4,
    designation: str = "Senior Specialist",
) -> RankedContributor:
    stats = ContributorStats(
        name=name,
        email=f"{name.lower()}@example.com",
        commit_count=commit_count,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        active_days=max(1, commit_count // 2),
        first_commit_date=datetime.date(2024, 1, 1),
        last_commit_date=datetime.date(2024, 3, 31),
    )
    return RankedContributor(
        stats=stats,
        composite_score=0.5,
        percentile=50.0,
        tier=tier,
        tier_designation=designation,
    )


def _is_valid_chart_json(value: str) -> bool:
    """Return True if value is a non-null JSON string with 'data' and 'layout' keys."""
    if value == "null":
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return "data" in parsed and "layout" in parsed


@pytest.mark.unit
class TestRenderJson:
    """Tests for Renderer.render_json."""

    def _renderer(self) -> Renderer:
        return Renderer()

    def _sample_data(self) -> ReportData:
        ranked = [_make_ranked("Alice", commit_count=10)]
        metadata = RepositoryMetadata(
            name="test-repo",
            remote_url=None,
            analysed_branch="main",
            total_commits=10,
            unique_contributors=1,
            analysis_since=datetime.date(2024, 1, 1),
            analysis_until=datetime.date(2024, 3, 31),
            generated_at=datetime.datetime(2024, 4, 1, 12, 0, tzinfo=datetime.UTC),
        )
        return ReportData(
            metadata=metadata,
            provenance=_PROVENANCE,
            ranked_contributors=ranked,
            commits=[],
        )

    def test_output_is_valid_json(self, tmp_path: Path) -> None:
        output = tmp_path / "report.json"
        self._renderer().render_json(self._sample_data(), output)
        parsed = json.loads(output.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)

    def test_output_contains_expected_top_level_keys(self, tmp_path: Path) -> None:
        output = tmp_path / "report.json"
        self._renderer().render_json(self._sample_data(), output)
        parsed = json.loads(output.read_text(encoding="utf-8"))
        assert "metadata" in parsed
        assert "contributors" in parsed
        assert "derived" in parsed

    def test_derived_metrics_use_the_honest_key_names(self, tmp_path: Path) -> None:
        """The payload reports commit concentration, never 'bus_factor'.

        The old key claimed to measure knowledge concentration while
        computing commit share. Consumers must not see it again.
        """
        output = tmp_path / "report.json"
        self._renderer().render_json(self._sample_data(), output)
        derived = json.loads(output.read_text(encoding="utf-8"))["derived"]
        assert "commit_concentration" in derived
        assert "bus_factor" not in derived

    def test_dates_serialised_as_iso_strings(self, tmp_path: Path) -> None:
        output = tmp_path / "report.json"
        self._renderer().render_json(self._sample_data(), output)
        metadata = json.loads(output.read_text(encoding="utf-8"))["metadata"]
        assert metadata["analysis_since"] == "2024-01-01"
        assert metadata["analysis_until"] == "2024-03-31"

    def test_returns_resolved_absolute_path(self, tmp_path: Path) -> None:
        output = tmp_path / "report.json"
        result = self._renderer().render_json(self._sample_data(), output)
        assert result.is_absolute()
        assert result == output.resolve()

    def test_raises_output_path_error_on_missing_parent(self, tmp_path: Path) -> None:
        output = tmp_path / "nonexistent" / "report.json"
        with pytest.raises(OutputPathError):
            self._renderer().render_json(self._sample_data(), output)


@pytest.mark.unit
class TestRenderCsv:
    """Tests for Renderer.render_csv."""

    _EXPECTED_FIELDNAMES: ClassVar[list[str]] = [
        "rank",
        "name",
        "email",
        "designation",
        "tier",
        "commits",
        "lines_added",
        "lines_deleted",
        "net_lines",
        "active_days",
        "last_commit_date",
        "composite_score",
        "percentile",
    ]

    def _renderer(self) -> Renderer:
        return Renderer()

    def _sample_data(self) -> ReportData:
        ranked = [
            _make_ranked("Alice", commit_count=10),
            _make_ranked("Bob", commit_count=5),
        ]
        metadata = RepositoryMetadata(
            name="test-repo",
            remote_url=None,
            analysed_branch="main",
            total_commits=15,
            unique_contributors=2,
            analysis_since=datetime.date(2024, 1, 1),
            analysis_until=datetime.date(2024, 3, 31),
            generated_at=datetime.datetime(2024, 4, 1, 12, 0, tzinfo=datetime.UTC),
        )
        return ReportData(
            metadata=metadata,
            provenance=_PROVENANCE,
            ranked_contributors=ranked,
            commits=[],
        )

    def test_header_row_contains_expected_columns(self, tmp_path: Path) -> None:
        output = tmp_path / "report.csv"
        self._renderer().render_csv(self._sample_data(), output)
        with output.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            assert list(reader.fieldnames or []) == self._EXPECTED_FIELDNAMES

    def test_bom_present_at_file_start(self, tmp_path: Path) -> None:
        output = tmp_path / "report.csv"
        self._renderer().render_csv(self._sample_data(), output)
        assert output.read_bytes()[:3] == b"\xef\xbb\xbf"

    def test_correct_row_count(self, tmp_path: Path) -> None:
        output = tmp_path / "report.csv"
        self._renderer().render_csv(self._sample_data(), output)
        with output.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        assert len(rows) == 3  # 1 header + 2 data rows

    def test_returns_resolved_absolute_path(self, tmp_path: Path) -> None:
        output = tmp_path / "report.csv"
        result = self._renderer().render_csv(self._sample_data(), output)
        assert result.is_absolute()
        assert result == output.resolve()

    def test_raises_output_path_error_on_missing_parent(self, tmp_path: Path) -> None:
        output = tmp_path / "nonexistent" / "report.csv"
        with pytest.raises(OutputPathError):
            self._renderer().render_csv(self._sample_data(), output)


# ------------------------------------------------------------------
# _compute_commit_concentration
# ------------------------------------------------------------------


@pytest.mark.unit
class TestComputeCommitConcentration:
    """Tests for the commit concentration derived metric helper."""

    def test_empty_ranked_returns_zero(self) -> None:
        assert _compute_commit_concentration([]) == 0

    def test_single_contributor_returns_one(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=20)]
        assert _compute_commit_concentration(ranked) == 1

    def test_two_equal_contributors_returns_one(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=10),
            _make_ranked("Bob", commit_count=10),
        ]
        assert _compute_commit_concentration(ranked) == 1

    def test_skewed_distribution_returns_one(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=90),
            _make_ranked("Bob", commit_count=5),
            _make_ranked("Carol", commit_count=5),
        ]
        assert _compute_commit_concentration(ranked) == 1

    def test_even_distribution_across_four_returns_two(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=25),
            _make_ranked("Bob", commit_count=25),
            _make_ranked("Carol", commit_count=25),
            _make_ranked("Dan", commit_count=25),
        ]
        assert _compute_commit_concentration(ranked) == 2

    def test_zero_total_commits_returns_zero(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=0)]
        assert _compute_commit_concentration(ranked) == 0


# ------------------------------------------------------------------
# _compute_longest_inactive_streak
# ------------------------------------------------------------------


@pytest.mark.unit
class TestComputeLongestInactiveStreak:
    """Tests for the inactive streak derived metric helper."""

    def test_no_commits_returns_full_window_length(self) -> None:
        streak = _compute_longest_inactive_streak(
            commits=[],
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 10),
        )
        assert streak == 9

    def test_commits_every_day_returns_zero(self) -> None:
        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 1, 5)
        commits = [_make_commit(start + datetime.timedelta(days=i)) for i in range(5)]
        assert (
            _compute_longest_inactive_streak(commits=commits, window_start=start, window_end=end)
            == 0
        )

    def test_gap_in_the_middle_is_detected(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 1)),
            _make_commit(datetime.date(2024, 1, 8)),
        ]
        streak = _compute_longest_inactive_streak(
            commits=commits,
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 10),
        )
        assert streak == 6

    def test_gap_at_start_of_window_is_detected(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 5))]
        streak = _compute_longest_inactive_streak(
            commits=commits,
            window_start=datetime.date(2024, 1, 1),
            window_end=datetime.date(2024, 1, 5),
        )
        assert streak == 4


# ------------------------------------------------------------------
# _build_timeline_chart
# ------------------------------------------------------------------


@pytest.mark.unit
class TestSanitiseChartLabel:
    """Tests for the _sanitise_chart_label helper."""

    def test_plain_string_passes_through_unchanged(self) -> None:
        assert _sanitise_chart_label("Alice Smith") == "Alice Smith"

    def test_html_tag_stripped(self) -> None:
        assert _sanitise_chart_label("Alice <b>Smith</b>") == "Alice Smith"

    def test_script_tag_stripped(self) -> None:
        assert _sanitise_chart_label("<script>alert(1)</script>Alice") == "Alice"

    def test_null_byte_stripped(self) -> None:
        assert _sanitise_chart_label("Alice\x00Smith") == "AliceSmith"

    def test_surrounding_whitespace_trimmed(self) -> None:
        assert _sanitise_chart_label("  Alice  ") == "Alice"

    def test_ampersand_preserved(self) -> None:
        assert _sanitise_chart_label("Alice & Bob") == "Alice & Bob"

    def test_parentheses_preserved(self) -> None:
        assert _sanitise_chart_label("Alice (Smith)") == "Alice (Smith)"


@pytest.mark.unit
class TestBuildTimelineChart:
    """Tests for the weekly commit timeline chart builder."""

    def test_empty_commits_returns_null_sentinel(self) -> None:
        assert _build_timeline_chart([]) == "null"

    def test_with_commits_returns_valid_chart_json(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 15)),
            _make_commit(datetime.date(2024, 2, 5)),
        ]
        assert _is_valid_chart_json(_build_timeline_chart(commits))

    def test_aggregates_commits_within_same_week_without_error(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 9)),
        ]
        assert _is_valid_chart_json(_build_timeline_chart(commits))

    def test_layout_does_not_contain_bgcolor_keys(self) -> None:
        commits = [_make_commit(datetime.date(2024, 1, 8))]
        parsed = json.loads(_build_timeline_chart(commits))
        layout = parsed.get("layout", {})
        assert "paper_bgcolor" not in layout
        assert "plot_bgcolor" not in layout

    def test_xaxis_type_is_category(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 1, 8)),
            _make_commit(datetime.date(2024, 1, 15)),
        ]
        result = json.loads(_build_timeline_chart(commits))
        assert result["layout"]["xaxis"]["type"] == "category"


@pytest.mark.unit
class TestBuildContributorTimelineChart:
    """Tests for the per-contributor weekly commit frequency chart builder."""

    def test_empty_commits_returns_null_sentinel(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=10),
            _make_ranked("Bob", commit_count=5),
        ]
        assert _build_contributor_timeline_chart([], ranked) == "null"

    def test_single_contributor_returns_null_sentinel(self) -> None:
        commits = [_make_commit(datetime.date(2024, 3, 11), email="alice@example.com")]
        ranked = [_make_ranked("Alice", commit_count=1)]
        assert _build_contributor_timeline_chart(commits, ranked) == "null"

    def test_two_contributors_return_valid_chart_json(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 11), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 18), email="bob@example.com"),
        ]
        ranked = [
            _make_ranked("Alice", commit_count=1),
            _make_ranked("Bob", commit_count=1),
        ]
        assert _is_valid_chart_json(_build_contributor_timeline_chart(commits, ranked))

    def test_returns_one_trace_per_contributor(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 11), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 18), email="bob@example.com"),
            _make_commit(datetime.date(2024, 3, 25), email="carol@example.com"),
        ]
        ranked = [
            _make_ranked("Alice", commit_count=1),
            _make_ranked("Bob", commit_count=1),
            _make_ranked("Carol", commit_count=1),
        ]
        parsed = json.loads(_build_contributor_timeline_chart(commits, ranked))
        assert len(parsed["data"]) == 3

    def test_xaxis_type_is_category(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 11), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 18), email="bob@example.com"),
        ]
        ranked = [
            _make_ranked("Alice", commit_count=1),
            _make_ranked("Bob", commit_count=1),
        ]
        parsed = json.loads(_build_contributor_timeline_chart(commits, ranked))
        assert parsed["layout"]["xaxis"]["type"] == "category"

    def test_layout_does_not_contain_bgcolor_keys(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 11), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 18), email="bob@example.com"),
        ]
        ranked = [
            _make_ranked("Alice", commit_count=1),
            _make_ranked("Bob", commit_count=1),
        ]
        parsed = json.loads(_build_contributor_timeline_chart(commits, ranked))
        layout = parsed["layout"]
        assert "paper_bgcolor" not in layout
        assert "plot_bgcolor" not in layout

    def test_script_closing_tag_is_escaped(self) -> None:
        """A contributor name containing </script> must not appear raw in output."""
        commits = [
            _make_commit(datetime.date(2024, 3, 11), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 18), email="bob@example.com"),
        ]
        injected_stats = ContributorStats(
            name="</script><script>alert(1)</script>",
            email="alice@example.com",
            commit_count=1,
            lines_added=10,
            lines_deleted=2,
            active_days=1,
            first_commit_date=datetime.date(2024, 1, 1),
            last_commit_date=datetime.date(2024, 3, 31),
        )
        ranked = [
            RankedContributor(
                stats=injected_stats,
                composite_score=1.0,
                percentile=100.0,
                tier=7,
                tier_designation="Commander",
            ),
            _make_ranked("Bob", commit_count=1),
        ]
        result = _build_contributor_timeline_chart(commits, ranked)
        assert "</script>" not in result


# ------------------------------------------------------------------
# _build_heatmap_chart — dispatch and granularity variants
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildHeatmapData:
    """Tests for the compact heatmap daily-count payload builder."""

    def test_empty_commits_returns_valid_json_with_empty_aggregated_counts(
        self,
    ) -> None:
        result = _build_heatmap_data([], [], datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
        parsed = json.loads(result)
        assert parsed["daily_counts"]["__aggregated__"] == {}

    def test_years_span_full_analysis_window(self) -> None:
        result = _build_heatmap_data([], [], datetime.date(2022, 6, 1), datetime.date(2024, 3, 31))
        assert json.loads(result)["years"] == [2022, 2023, 2024]

    def test_single_year_window_produces_one_year(self) -> None:
        result = _build_heatmap_data([], [], datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
        assert json.loads(result)["years"] == [2024]

    def test_aggregated_contributor_is_always_first(self) -> None:
        result = _build_heatmap_data([], [], datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
        assert json.loads(result)["contributors"][0]["email"] == "__aggregated__"

    def test_aggregated_counts_sum_all_contributors(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 15), email="a@example.com"),
            _make_commit(datetime.date(2024, 3, 15), email="b@example.com"),
            _make_commit(datetime.date(2024, 3, 20), email="a@example.com"),
        ]
        result = _build_heatmap_data(
            commits, [], datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        agg = json.loads(result)["daily_counts"]["__aggregated__"]
        assert agg["2024-03-15"] == 2
        assert agg["2024-03-20"] == 1

    def test_per_contributor_counts_keyed_by_lowercased_email(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 15), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 15), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 20), email="bob@example.com"),
        ]
        ranked = [
            _make_ranked("Alice", commit_count=2),
            _make_ranked("Bob", commit_count=1),
        ]
        result = _build_heatmap_data(
            commits, ranked, datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        counts = json.loads(result)["daily_counts"]
        assert counts["alice@example.com"]["2024-03-15"] == 2
        assert counts["bob@example.com"]["2024-03-20"] == 1

    def test_contributor_list_follows_ranked_order(self) -> None:
        commits = [
            _make_commit(datetime.date(2024, 3, 15), email="alice@example.com"),
            _make_commit(datetime.date(2024, 3, 20), email="bob@example.com"),
        ]
        ranked = [
            _make_ranked("Alice", commit_count=5),
            _make_ranked("Bob", commit_count=2),
        ]
        result = _build_heatmap_data(
            commits, ranked, datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        contributors = json.loads(result)["contributors"]
        assert contributors[0]["email"] == "__aggregated__"
        assert contributors[1]["email"] == "alice@example.com"
        assert contributors[2]["email"] == "bob@example.com"

    def test_payload_contains_required_top_level_keys(self) -> None:
        result = _build_heatmap_data([], [], datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
        parsed = json.loads(result)
        assert "years" in parsed
        assert "contributors" in parsed
        assert "daily_counts" in parsed

    def test_script_closing_tag_is_escaped(self) -> None:
        """</script> in any embedded string must not appear raw in the output."""
        commits = [_make_commit(datetime.date(2024, 3, 15))]
        result = _build_heatmap_data(
            commits, [], datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        assert "</script>" not in result


# ------------------------------------------------------------------
# _build_contributor_commits_chart
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContributorCommitsChart:
    """Tests for the horizontal commit count bar chart builder."""

    def test_empty_ranked_returns_null_sentinel(self) -> None:
        assert _build_contributor_commits_chart([]) == "null"

    def test_single_contributor_returns_valid_chart_json(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=15)]
        assert _is_valid_chart_json(_build_contributor_commits_chart(ranked))

    def test_multiple_contributors_return_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=30),
            _make_ranked("Bob", commit_count=12),
            _make_ranked("Carol", commit_count=5),
        ]
        assert _is_valid_chart_json(_build_contributor_commits_chart(ranked))

    @pytest.mark.parametrize(
        "injected_name,expected_absent",
        [
            ("<b>Alice</b>", "<b>"),
            ("<script>alert(1)</script>Alice", "<script>"),
            ("Alice\x00Smith", "\x00"),
        ],
    )
    def test_html_injection_stripped_from_labels(
        self,
        injected_name: str,
        expected_absent: str,
    ) -> None:
        """User-controlled strings containing HTML must not appear raw in chart output."""
        ranked = [
            _make_ranked(injected_name, commit_count=10),
            _make_ranked("Bob", commit_count=5),
        ]
        result = _build_contributor_commits_chart(ranked)
        assert expected_absent not in result


# ------------------------------------------------------------------
# _build_contributor_lines_chart
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContributorLinesChart:
    """Tests for the grouped lines changed bar chart builder."""

    def test_empty_ranked_returns_null_sentinel(self) -> None:
        assert _build_contributor_lines_chart([]) == "null"

    def test_single_contributor_returns_valid_chart_json(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=10, lines_added=500, lines_deleted=80)]
        assert _is_valid_chart_json(_build_contributor_lines_chart(ranked))

    def test_multiple_contributors_return_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20, lines_added=1200, lines_deleted=300),
            _make_ranked("Bob", commit_count=8, lines_added=400, lines_deleted=100),
        ]
        assert _is_valid_chart_json(_build_contributor_lines_chart(ranked))

    def test_chart_contains_two_traces_for_added_and_deleted(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=10),
            _make_ranked("Bob", commit_count=5),
        ]
        parsed = json.loads(_build_contributor_lines_chart(ranked))
        assert len(parsed["data"]) == 2


# ------------------------------------------------------------------
# _build_commit_share_pie and _build_lines_share_pie
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBuildPieCharts:
    """Tests for the commit share and lines share donut charts."""

    def test_single_contributor_commits_returns_null_sentinel(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=10)]
        assert _build_commit_share_pie(ranked) == "null"

    def test_single_contributor_lines_returns_null_sentinel(self) -> None:
        ranked = [_make_ranked("Alice", commit_count=10)]
        assert _build_lines_share_pie(ranked) == "null"

    def test_two_contributors_commits_returns_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20),
            _make_ranked("Bob", commit_count=10),
        ]
        assert _is_valid_chart_json(_build_commit_share_pie(ranked))

    def test_two_contributors_lines_returns_valid_chart_json(self) -> None:
        ranked = [
            _make_ranked("Alice", commit_count=20, lines_added=800, lines_deleted=100),
            _make_ranked("Bob", commit_count=5, lines_added=200, lines_deleted=40),
        ]
        assert _is_valid_chart_json(_build_lines_share_pie(ranked))

    def test_pie_trace_has_hole_property(self) -> None:
        """Confirms the donut form: hole must be present and non-zero."""
        ranked = [
            _make_ranked("Alice", commit_count=20),
            _make_ranked("Bob", commit_count=10),
        ]
        parsed = json.loads(_build_commit_share_pie(ranked))
        hole = parsed["data"][0].get("hole")
        assert hole is not None
        assert hole > 0


# ------------------------------------------------------------------
# _aggregate_pie_data
# ------------------------------------------------------------------


@pytest.mark.unit
class TestAggregatePieData:
    """Tests for the pie data aggregation helper."""

    def test_fewer_than_max_slices_returned_unchanged(self) -> None:
        items = [("Alice", 10), ("Bob", 8), ("Carol", 5)]
        labels, values = _aggregate_pie_data(items)
        assert labels == ["Alice", "Bob", "Carol"]
        assert values == [10, 8, 5]

    def test_exactly_max_slices_returned_unchanged(self) -> None:
        items = [(f"Contributor{i}", 10 - i) for i in range(_PIE_MAX_SLICES)]
        labels, _values = _aggregate_pie_data(items)
        assert len(labels) == _PIE_MAX_SLICES
        assert "Other Contributors" not in labels

    def test_beyond_max_slices_aggregates_remainder(self) -> None:
        """The cap is the palette length: past it there is no colour left."""
        items = [(f"Contributor{i}", 10) for i in range(_PIE_MAX_SLICES + 2)]
        labels, values = _aggregate_pie_data(items)
        assert len(labels) == _PIE_MAX_SLICES + 1
        assert labels[-1] == "Other Contributors"
        assert values[-1] == 20

    def test_aggregate_value_is_sum_of_remainder(self) -> None:
        items = [(chr(65 + i), (10 - i) * 10) for i in range(_PIE_MAX_SLICES + 3)]
        labels, values = _aggregate_pie_data(items)
        expected = sum(value for _label, value in items[_PIE_MAX_SLICES:])
        assert values[-1] == expected
        assert labels[-1] == "Other Contributors"
        assert sum(values) == sum(value for _label, value in items), (
            "aggregating must not lose or invent commits"
        )

    def test_output_lengths_are_equal(self) -> None:
        items = [(f"C{i}", i + 1) for i in range(15)]
        labels, values = _aggregate_pie_data(items)
        assert len(labels) == len(values)


# ------------------------------------------------------------------
# _to_json — security and type contract
# ------------------------------------------------------------------


@pytest.mark.unit
class TestToJson:
    """Tests for the Plotly figure JSON serialisation helper."""

    def _simple_figure(self) -> go.Figure:
        fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))
        return fig

    def test_returns_valid_json_string(self) -> None:
        result = _to_json(self._simple_figure())
        parsed = json.loads(result)
        assert "data" in parsed
        assert "layout" in parsed

    def test_paper_bgcolor_absent_from_output(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(paper_bgcolor="#ffffff")
        result = _to_json(fig)
        layout = json.loads(result)["layout"]
        assert "paper_bgcolor" not in layout

    def test_plot_bgcolor_absent_from_output(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(plot_bgcolor="#f0f0f0")
        result = _to_json(fig)
        layout = json.loads(result)["layout"]
        assert "plot_bgcolor" not in layout

    def test_font_color_absent_from_output(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(font={"color": "#000000", "size": 12})
        result = _to_json(fig)
        font = json.loads(result)["layout"].get("font", {})
        assert "color" not in font

    def test_font_size_preserved_after_color_removal(self) -> None:
        fig = self._simple_figure()
        fig.update_layout(font={"color": "#000000", "size": 14})
        result = _to_json(fig)
        font = json.loads(result)["layout"].get("font", {})
        assert font.get("size") == 14

    def test_script_closing_tag_in_label_is_escaped(self) -> None:
        """A label containing </script> must not produce a raw closing tag."""
        fig = go.Figure(go.Bar(x=["</script>"], y=[1]))
        result = _to_json(fig)
        assert "</script>" not in result
        assert "<\\/script>" in result
