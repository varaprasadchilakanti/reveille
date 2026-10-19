# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The heatmap opens on the latest year with a commit, not on an empty one.

The window runs to today, so a history that stopped in 2023 opened on a blank
2026 grid, the first thing a reader of a dormant repository saw.
"""

from __future__ import annotations

import datetime
import json

import pytest

from reveille.adapters.renderer import _build_heatmap_data
from reveille.domain.models import Commit, ContributorStats, RankedContributor

pytestmark = pytest.mark.unit


def _payload(commit_day: datetime.date, until: datetime.date) -> dict[str, object]:
    stamp = datetime.datetime.combine(commit_day, datetime.time(10), tzinfo=datetime.UTC)
    stats = ContributorStats("A", "a@e.test", 1, 1, 0, 1, commit_day, commit_day)
    ranked = [RankedContributor(stats, 0.0, 0.0, 1, "")]
    commit = Commit("0" * 40, "A", "a@e.test", stamp, 1, 0)
    return json.loads(_build_heatmap_data([commit], ranked, commit_day, until))  # type: ignore[no-any-return]


def test_a_history_that_stopped_opens_on_its_last_year() -> None:
    payload = _payload(datetime.date(2023, 3, 28), datetime.date(2026, 10, 17))

    assert payload["years"] == [2023, 2024, 2025, 2026]
    assert payload["default_year"] == 2023


def test_an_active_history_opens_on_this_year() -> None:
    payload = _payload(datetime.date(2026, 10, 1), datetime.date(2026, 10, 17))

    assert payload["default_year"] == 2026


def test_the_page_starts_on_the_year_it_is_given() -> None:
    from importlib.resources import files

    template = (files("reveille") / "templates" / "report.html.j2").read_text(encoding="utf-8")

    assert "currentYear        = heatmapData.default_year ||" in template
