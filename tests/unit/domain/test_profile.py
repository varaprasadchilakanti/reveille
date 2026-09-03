# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The repository profile: five naturally bounded shares.

The design constraint is that no axis is rescaled by a constant. A radar
whose axes are normalised by invented factors can be given any silhouette
its author wants, and a reader has no way to tell. These tests hold that
line: every axis stays inside 0..1 by construction, the order is fixed,
and the extremes land where the definition says they should.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.models import Commit, ContributorStats, FileStats
from reveille.domain.profile import AXIS_ORDER, repository_profile

_SINCE = datetime.date(2026, 1, 1)
_UNTIL = datetime.date(2026, 3, 31)


def _commit(day: int, added: int = 10, deleted: int = 0, email: str = "a@x") -> Commit:
    return Commit(
        sha=f"{day:040d}",
        author_name="Dev",
        author_email=email,
        timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(days=day),
        lines_added=added,
        lines_deleted=deleted,
    )


def _contributor(email: str, commits: int) -> ContributorStats:
    return ContributorStats(
        name=email,
        email=email,
        commit_count=commits,
        lines_added=1,
        lines_deleted=0,
        active_days=1,
        first_commit_date=_SINCE,
        last_commit_date=_UNTIL,
    )


def _file(path: str, commits: int) -> FileStats:
    return FileStats(path=path, commits=commits, lines_added=10, lines_deleted=0)


def _profile(commits, contributors, files):
    return {
        a.name: a.value for a in repository_profile(commits, contributors, files, _SINCE, _UNTIL)
    }


@pytest.mark.unit
class TestEveryAxisIsABoundedShare:
    """Nothing is rescaled, so nothing can leave 0..1."""

    def test_all_axes_stay_within_range_on_extreme_input(self) -> None:
        commits = [_commit(day, added=99999) for day in range(90)]
        contributors = [_contributor(f"c{i}@x", 1000) for i in range(50)]
        files = [_file(f"f{i}.py", 99) for i in range(200)]
        for name, value in _profile(commits, contributors, files).items():
            assert 0.0 <= value <= 1.0, f"{name} is {value}, outside 0..1"

    def test_a_commit_outside_the_window_cannot_push_continuity_over_one(self) -> None:
        commits = [_commit(day) for day in range(400)]
        assert _profile(commits, [_contributor("a@x", 400)], [])["Continuity"] <= 1.0


@pytest.mark.unit
class TestTheAxisOrderIsFixed:
    """Permuting axes changes the drawn shape without changing a number."""

    def test_order_matches_the_declared_contract(self) -> None:
        commits = [_commit(1)]
        axes = repository_profile(commits, [_contributor("a@x", 1)], [], _SINCE, _UNTIL)
        assert [a.name for a in axes] == list(AXIS_ORDER)

    def test_order_does_not_depend_on_the_values(self) -> None:
        low = repository_profile([_commit(1)], [_contributor("a@x", 1)], [], _SINCE, _UNTIL)
        high = repository_profile(
            [_commit(d) for d in range(90)],
            [_contributor(f"c{i}@x", 10) for i in range(5)],
            [_file(f"f{i}.py", 5) for i in range(10)],
            _SINCE,
            _UNTIL,
        )
        assert [a.name for a in low] == [a.name for a in high] == list(AXIS_ORDER)


@pytest.mark.unit
class TestTheExtremesLandWhereTheDefinitionSays:
    """Each axis is checked against a case with a known answer."""

    def test_perfectly_even_contributors_give_full_spread(self) -> None:
        contributors = [_contributor(f"c{i}@x", 10) for i in range(4)]
        assert _profile([_commit(1)], contributors, [])["Spread"] == pytest.approx(1.0)

    def test_a_single_contributor_gives_no_spread(self) -> None:
        """A Gini over one person is undefined; the honest answer is zero."""
        assert _profile([_commit(1)], [_contributor("a@x", 5)], [])["Spread"] == 0.0

    def test_a_commit_every_week_gives_full_continuity(self) -> None:
        commits = [_commit(day) for day in range(0, 90, 7)]
        assert _profile(commits, [_contributor("a@x", 13)], [])["Continuity"] > 0.9

    def test_one_commit_at_the_start_gives_almost_no_continuity(self) -> None:
        assert _profile([_commit(0)], [_contributor("a@x", 1)], [])["Continuity"] < 0.1

    def test_all_work_in_the_final_quarter_gives_full_recent_work(self) -> None:
        span = (_UNTIL - _SINCE).days
        commits = [_commit(span - offset) for offset in range(5)]
        assert _profile(commits, [_contributor("a@x", 5)], [])["Recent work"] == 1.0

    def test_work_only_at_the_start_gives_no_recent_work(self) -> None:
        assert _profile([_commit(0)], [_contributor("a@x", 1)], [])["Recent work"] == 0.0

    def test_the_axis_is_not_degenerate_under_deterministic_windows(self) -> None:
        """The axis it replaced was identically 1.0 whenever the window
        ended at the last commit -- which is what `--deterministic` does,
        and what the Playbook tells consumers to pass."""
        early = [_commit(0), _commit(1)]
        last = max(c.timestamp.date() for c in early)
        axes = repository_profile(early, [_contributor("a@x", 2)], [], _SINCE, last)
        recent = {a.name: a.value for a in axes}["Recent work"]
        assert recent < 1.0, "the axis carries no information in this mode"

    def test_files_touched_once_give_no_revisiting(self) -> None:
        files = [_file(f"f{i}.py", 1) for i in range(5)]
        assert _profile([_commit(1)], [_contributor("a@x", 1)], files)["Revisiting"] == 0.0

    def test_generated_files_do_not_count_towards_revisiting(self) -> None:
        """A lock file's revision count reflects tooling, not work."""
        files = [_file("poetry.lock", 50), _file("a.py", 1)]
        assert _profile([_commit(1)], [_contributor("a@x", 1)], files)["Revisiting"] == 0.0

    def test_all_small_commits_give_full_small_steps(self) -> None:
        commits = [_commit(day, added=10) for day in range(5)]
        assert _profile(commits, [_contributor("a@x", 5)], [])["Small steps"] == 1.0

    def test_all_large_commits_give_none(self) -> None:
        commits = [_commit(day, added=5000) for day in range(5)]
        assert _profile(commits, [_contributor("a@x", 5)], [])["Small steps"] == 0.0

    def test_churn_not_net_decides_small_steps(self) -> None:
        """A commit that adds 150 and deletes 150 changed 300 lines."""
        commits = [_commit(1, added=150, deleted=150)]
        assert _profile(commits, [_contributor("a@x", 1)], [])["Small steps"] == 0.0


@pytest.mark.unit
class TestItRefusesToProfileNothing:
    def test_no_commits_yields_no_axes(self) -> None:
        assert repository_profile([], [], [], _SINCE, _UNTIL) == []

    def test_a_zero_length_window_does_not_divide_by_zero(self) -> None:
        axes = repository_profile([_commit(0)], [_contributor("a@x", 1)], [], _SINCE, _SINCE)
        assert len(axes) == len(AXIS_ORDER)


@pytest.mark.unit
class TestItNamesNobody:
    def test_no_axis_carries_an_identity(self) -> None:
        axes = repository_profile(
            [_commit(1)], [_contributor("someone@example.com", 1)], [], _SINCE, _UNTIL
        )
        rendered = " ".join(f"{a.name} {a.description}" for a in axes)
        assert "someone@example.com" not in rendered
        assert "@" not in rendered


@pytest.mark.unit
class TestSpreadIsComparableAcrossTeamSizes:
    """The raw `1 - Gini` was rescaled by headcount, and nothing caught it.

    Gini's maximum for a sample of n is (n-1)/n, so `1 - Gini` has a
    floor of 1/n rather than 0. Measured before the fix: adding a
    contributor who committed *nothing* moved Spread from 0% to 50%, and
    ten people where one did everything scored 10% while two people
    where one did everything scored 50% — the more concentrated
    repository scoring five times higher.

    This contradicted the module's own stated design, that every axis is
    a bounded share and none is rescaled. Eighteen tests passed over it,
    one of which encoded the wrong value as intended behaviour.
    """

    def _spread_of(self, counts: list[int]) -> float:
        people = [_contributor(f"c{i}@x", n) for i, n in enumerate(counts)]
        return _profile([_commit(1)], people, [])["Spread"]

    @pytest.mark.parametrize("size", [2, 3, 5, 10])
    def test_maximum_concentration_scores_zero_at_every_team_size(self, size: int) -> None:
        counts = [100] + [0] * (size - 1)
        assert self._spread_of(counts) == pytest.approx(0.0, abs=1e-9), (
            f"one person doing everything among {size} scores "
            f"{self._spread_of(counts):.0%}; it must be 0% at any size"
        )

    @pytest.mark.parametrize("size", [2, 3, 5, 10])
    def test_a_perfectly_even_team_scores_one_at_every_team_size(self, size: int) -> None:
        assert self._spread_of([10] * size) == pytest.approx(1.0)

    def test_adding_an_idle_contributor_does_not_raise_spread(self) -> None:
        """The clearest form of the defect: a person who does nothing."""
        before = self._spread_of([100])
        after = self._spread_of([100, 0])
        assert after <= before + 1e-9, (
            f"adding a contributor with no commits moved Spread from {before:.0%} to {after:.0%}"
        )

    def test_a_more_concentrated_repository_never_scores_higher(self) -> None:
        even = self._spread_of([10, 10, 10, 10])
        lopsided = self._spread_of([37, 1, 1, 1])
        assert lopsided < even
