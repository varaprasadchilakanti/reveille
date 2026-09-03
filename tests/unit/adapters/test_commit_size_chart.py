# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The change-size histogram: every commit counted, in the right bucket."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from reveille.adapters.renderer import _build_commit_size_chart
from reveille.domain.models import Commit

_TEMPLATE = Path(__file__).resolve().parents[3] / "src/reveille/templates/report.html.j2"


def _commit(added: int, deleted: int = 0) -> Commit:
    return Commit(
        sha="0" * 40,
        author_name="Dev",
        author_email="dev@example.com",
        timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        lines_added=added,
        lines_deleted=deleted,
    )


def _figure(commits: list[Commit]) -> dict:
    return json.loads(_build_commit_size_chart(commits))


@pytest.mark.unit
class TestEveryCommitIsCounted:
    """A histogram that drops a commit misstates the distribution."""

    def test_totals_match_the_input(self) -> None:
        commits = [_commit(n) for n in (1, 5, 12, 60, 300, 1500, 20000)]
        trace = _figure(commits)["data"][0]
        assert sum(trace["y"]) == len(commits)

    def test_a_zero_line_commit_still_lands_in_the_first_bucket(self) -> None:
        """A commit that changes nothing measurable is still a commit."""
        trace = _figure([_commit(0, 0)])["data"][0]
        assert sum(trace["y"]) == 1
        assert trace["y"][0] == 1

    def test_deletions_count_towards_size(self) -> None:
        """Churn is added plus deleted, not net."""
        trace = _figure([_commit(0, 500)])["data"][0]
        assert trace["y"][3] == 1, "500 lines deleted belongs in the 200-999 bucket"

    @pytest.mark.parametrize(
        ("size", "bucket"),
        [
            (1, 0),
            (9, 0),
            (10, 1),
            (49, 1),
            (50, 2),
            (199, 2),
            (200, 3),
            (999, 3),
            (1000, 4),
            (4999, 4),
            (5000, 5),
            (99999, 5),
        ],
    )
    def test_boundaries_fall_on_the_documented_side(self, size: int, bucket: int) -> None:
        trace = _figure([_commit(size)])["data"][0]
        assert trace["y"][bucket] == 1, f"{size} lines landed outside bucket {bucket}"
        assert sum(trace["y"]) == 1


@pytest.mark.unit
class TestItIsWiredIntoTheReport:
    """A builder nothing renders is dead code."""

    def test_empty_history_produces_no_chart(self) -> None:
        assert _build_commit_size_chart([]) == "null"

    def test_the_template_embeds_and_draws_it(self) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        assert 'id="spec-commit_size"' in template
        assert "charts.commit_size | safe" in template, (
            "without `| safe` the specification is HTML-escaped and will not parse"
        )
        assert 'id="chart-commit_size"' in template
        assert "'commit_size'" in template, "the client script never initialises it"

    def test_the_rendered_report_contains_it(self, tmp_path: Path) -> None:
        from reveille.adapters.renderer import Renderer
        from tests.unit.adapters.test_lorenz_chart import _report_data

        out = tmp_path / "r.html"
        Renderer().render(_report_data([5, 3]), out)
        assert 'id="spec-commit_size"' in out.read_text(encoding="utf-8")

    def test_it_names_no_contributor(self) -> None:
        """A property of the history, not of anyone in it."""
        figure = _figure([_commit(10), _commit(20)])
        assert "Dev" not in json.dumps(figure)
        assert "dev@example.com" not in json.dumps(figure)
