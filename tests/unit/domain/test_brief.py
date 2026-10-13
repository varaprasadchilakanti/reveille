# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The counts a brief states, from constructed inputs (ADR 0022)."""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.brief import QUIET_DAYS, describe_range
from reveille.domain.models import AreaActivity, Commit, FileStats

_DAY = datetime.date(2026, 3, 1)


def _commit(email: str, name: str = "N", day: int = 0) -> Commit:
    stamp = datetime.datetime.combine(
        _DAY + datetime.timedelta(days=day), datetime.time(10), tzinfo=datetime.UTC
    )
    return Commit(
        sha=f"{day:040d}",
        author_name=name,
        author_email=email,
        timestamp=stamp,
        lines_added=0,
        lines_deleted=0,
    )


def _area(name: str, commits: int, first: datetime.date) -> AreaActivity:
    return AreaActivity(
        area=name, commits=commits, last_changed=first, authors={}, first_changed=first
    )


def test_people_and_automated_accounts_are_counted_apart() -> None:
    commits = [
        _commit("a@e.test"),
        _commit("A@E.TEST", day=1),
        _commit("x[bot]@users.noreply.github.com", "x[bot]", day=2),
    ]

    facts = describe_range(commits, [], [], 0, {})

    assert (facts.commits, facts.people, facts.automated) == (3, 1, 1)
    assert (facts.first, facts.last) == (_DAY, _DAY + datetime.timedelta(days=2))


def test_lists_are_ordered_by_count_then_name() -> None:
    files = [FileStats("b.py", 2, 0, 0), FileStats("a.md", 2, 0, 0), FileStats("c.py", 1, 0, 0)]
    areas = [_area("z", 1, _DAY), _area("b", 3, _DAY), _area("a", 3, _DAY)]

    facts = describe_range([_commit("a@e.test")], files, areas, 0, {})

    assert facts.file_types == ((".py", 3), (".md", 2))
    assert facts.areas == (("a", 3), ("b", 3), ("z", 1))


@pytest.mark.parametrize(("quiet", "active"), [(QUIET_DAYS, True), (QUIET_DAYS - 1, False)])
def test_active_again_needs_the_full_quiet_period(quiet: int, active: bool) -> None:
    before = _DAY - datetime.timedelta(days=quiet)
    facts = describe_range([_commit("a@e.test")], [], [_area("lib", 1, _DAY)], 0, {"lib": before})

    assert (facts.active_again == ("lib",)) is active


def test_an_area_with_no_earlier_history_is_not_active_again() -> None:
    facts = describe_range([_commit("a@e.test")], [], [_area("new", 1, _DAY)], 0, {"new": None})

    assert facts.active_again == ()


def test_an_empty_range_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one commit"):
        describe_range([], [], [], 0, {})
