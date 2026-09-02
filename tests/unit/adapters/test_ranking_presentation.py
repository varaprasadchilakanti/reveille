"""The ranking opt-in must be real in every output format.

From 0.8.0 the contributor ranking is off by default (ADR 0010). The switch
was honoured in the JSON payload but not in the two formats a person actually
reads: the HTML still rendered a section headed "Contributor Rankings", with a
rank number against every named individual and a screen-reader caption stating
they were "ordered by composite score" -- while every score was 0.0 and the
real ordering was by commit count. The CSV, one function below the JSON path
that omits these fields on purpose, still wrote `tier`, `composite_score` and
`percentile` as zeroes into the format most likely to be opened in a
spreadsheet and sorted.

Placeholder `RankedContributor` rows are built either way, so a truthiness test
on that list never was the gate. `provenance.ranking_enabled` is.
"""

from __future__ import annotations

import csv
import datetime
import json
from pathlib import Path

import pytest

from reveille.adapters.renderer import Renderer
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)

_RANKING_WEIGHTS = {"commits": 0.3, "lines": 0.25, "consistency": 0.25, "recency": 0.2}


def _provenance(*, ranking: bool) -> AnalysisProvenance:
    return AnalysisProvenance(
        reveille_version="0.0.0-test",
        schema_version=SCHEMA_VERSION,
        head_sha="0" * 40,
        requested_branch=None,
        requested_since=None,
        requested_until=None,
        exclude_authors_count=0,
        min_commits=1,
        ranking_enabled=ranking,
        ranking_weights=_RANKING_WEIGHTS if ranking else None,
        mailmap_applied=False,
        deterministic=False,
    )


def _data(*, ranking: bool) -> ReportData:
    """Two contributors, carrying the placeholder values used when ranking is off."""
    ranked = [
        RankedContributor(
            stats=ContributorStats(
                name=name,
                email=f"{name.lower()}@example.com",
                commit_count=count,
                lines_added=10,
                lines_deleted=1,
                active_days=3,
                first_commit_date=datetime.date(2024, 1, 1),
                last_commit_date=datetime.date(2024, 6, 1),
            ),
            composite_score=0.87 if ranking else 0.0,
            percentile=90.0 if ranking else 0.0,
            tier=1 if ranking else 0,
            tier_designation="Private" if ranking else "--",
        )
        for name, count in (("Alice", 9), ("Bob", 3))
    ]
    return ReportData(
        metadata=RepositoryMetadata(
            name="test-repo",
            remote_url=None,
            analysed_branch="main",
            total_commits=12,
            unique_contributors=2,
            analysis_since=datetime.date(2024, 1, 1),
            analysis_until=datetime.date(2024, 6, 1),
            generated_at=datetime.datetime(2024, 6, 2, 12, 0, tzinfo=datetime.UTC),
        ),
        provenance=_provenance(ranking=ranking),
        ranked_contributors=ranked,
        commits=[],
    )


def _html(tmp_path: Path, *, ranking: bool) -> str:
    out = tmp_path / "r.html"
    Renderer().render(_data(ranking=ranking), out)
    return out.read_text(encoding="utf-8")


def _csv_rows(tmp_path: Path, *, ranking: bool) -> list[dict[str, str]]:
    out = tmp_path / "r.csv"
    Renderer().render_csv(_data(ranking=ranking), out)
    with out.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.unit
class TestHtmlWithRankingOff:
    """The default report. None of the ranking framing may appear."""

    def test_no_rankings_heading(self, tmp_path: Path) -> None:
        assert "Contributor Rankings" not in _html(tmp_path, ranking=False)

    def test_no_rank_numbers_against_named_individuals(self, tmp_path: Path) -> None:
        assert 'class="rank-number"' not in _html(tmp_path, ranking=False)

    def test_no_tier_badges(self, tmp_path: Path) -> None:
        html = _html(tmp_path, ranking=False)
        assert 'class="tier-badge' not in html
        assert ">Designation<" not in html

    def test_no_score_column(self, tmp_path: Path) -> None:
        html = _html(tmp_path, ranking=False)
        assert 'class="score-bar-fill"' not in html
        assert ">Score<" not in html

    def test_caption_does_not_claim_an_ordering_that_does_not_exist(self, tmp_path: Path) -> None:
        html = _html(tmp_path, ranking=False)
        assert "ordered by composite score" not in html
        assert "ordered by commit count" in html

    def test_contributors_are_still_listed(self, tmp_path: Path) -> None:
        """Opting out of the ranking must not cost the underlying figures."""
        html = _html(tmp_path, ranking=False)
        assert "Alice" in html and "Bob" in html
        assert "Contributors" in html

    def test_rows_keep_a_header_cell_for_screen_readers(self, tmp_path: Path) -> None:
        """The rank cell was the row header; without it the name takes over."""
        assert 'th scope="row" class="row-header"' in _html(tmp_path, ranking=False)


@pytest.mark.unit
class TestHtmlWithRankingOn:
    """Asking for the ranking must still produce it -- the positive control."""

    def test_rankings_heading_returns(self, tmp_path: Path) -> None:
        assert "Contributor Rankings" in _html(tmp_path, ranking=True)

    def test_rank_numbers_designations_and_scores_return(self, tmp_path: Path) -> None:
        html = _html(tmp_path, ranking=True)
        assert 'class="rank-number"' in html
        assert 'class="tier-badge' in html
        assert 'class="score-bar-fill"' in html
        assert "ordered by composite score" in html


@pytest.mark.unit
class TestCsvWithRankingOff:
    """The format most likely to be sorted in a spreadsheet."""

    def test_ranking_columns_are_absent(self, tmp_path: Path) -> None:
        row = _csv_rows(tmp_path, ranking=False)[0]
        for field in ("designation", "tier", "composite_score", "percentile"):
            assert field not in row

    def test_no_zero_sentinels_are_emitted(self, tmp_path: Path) -> None:
        """A `0` is a number a reader can sort on; an absent column is not."""
        _csv_rows(tmp_path, ranking=False)
        text = (tmp_path / "r.csv").read_text(encoding="utf-8-sig")
        assert "--" not in text
        assert "0.0" not in text

    def test_the_real_figures_survive(self, tmp_path: Path) -> None:
        rows = _csv_rows(tmp_path, ranking=False)
        assert [r["name"] for r in rows] == ["Alice", "Bob"]
        assert rows[0]["commits"] == "9"
        assert rows[0]["active_days"] == "3"


@pytest.mark.unit
class TestCsvWithRankingOn:
    """The documented column set, unchanged, when the ranking is asked for."""

    def test_columns_match_the_documented_order(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        Renderer().render_csv(_data(ranking=True), out)
        header = out.read_text(encoding="utf-8-sig").splitlines()[0]
        assert header == (
            "rank,name,email,designation,tier,commits,lines_added,lines_deleted,"
            "net_lines,active_days,last_commit_date,composite_score,percentile"
        )

    def test_ranking_values_are_present(self, tmp_path: Path) -> None:
        row = _csv_rows(tmp_path, ranking=True)[0]
        assert row["tier"] == "1"
        assert row["designation"] == "Private"
        assert row["composite_score"] == "0.87"


@pytest.mark.unit
class TestJsonRemainsConsistent:
    """The path that was already correct, kept as the reference the others match."""

    def test_ranking_keys_absent_when_off(self, tmp_path: Path) -> None:
        out = tmp_path / "r.json"
        Renderer().render_json(_data(ranking=False), out)
        contributor = json.loads(out.read_text(encoding="utf-8"))["contributors"][0]
        for key in ("tier", "tier_designation", "composite_score", "percentile"):
            assert key not in contributor

    def test_ranking_keys_present_when_on(self, tmp_path: Path) -> None:
        out = tmp_path / "r.json"
        Renderer().render_json(_data(ranking=True), out)
        contributor = json.loads(out.read_text(encoding="utf-8"))["contributors"][0]
        for key in ("tier", "tier_designation", "composite_score", "percentile"):
            assert key in contributor

    def test_all_three_formats_agree_on_the_switch(self, tmp_path: Path) -> None:
        """The defect was one format honouring the flag and two ignoring it."""
        html = _html(tmp_path, ranking=False)
        csv_row = _csv_rows(tmp_path, ranking=False)[0]
        out = tmp_path / "r.json"
        Renderer().render_json(_data(ranking=False), out)
        json_row = json.loads(out.read_text(encoding="utf-8"))["contributors"][0]

        assert "composite_score" not in csv_row
        assert "composite_score" not in json_row
        assert 'class="score-bar-fill"' not in html
