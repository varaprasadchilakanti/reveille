# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The repository profile: three naturally bounded shares.

The design constraint is that no axis is rescaled by a constant. A figure
whose axes are normalised by invented factors can be given any shape its
author wants, and a reader has no way to tell. These tests hold that line:
every axis stays inside 0..1 by construction, the order is fixed, and the
extremes land where the definition says they should.

Two axes were removed at 0.9.0 and their absence is asserted here, because
each restated a figure the report prints elsewhere and both could be
reintroduced by someone who had not read ADR 0012.

The `expected` values are the other subject. They exist so a reader can tell
an ordinary figure from a notable one, and they are computed from each
measure's own arithmetic. A number somebody *chose* would be a target, and
these tests pin the formulas so that distinction cannot quietly erode.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.models import Commit, FileStats
from reveille.domain.profile import AXIS_ORDER, repository_profile

_SINCE = datetime.date(2026, 1, 1)
_UNTIL = datetime.date(2026, 3, 31)

#: The window above: 89 days, so 13 whole-or-partial weeks.
_SPAN_DAYS = (_UNTIL - _SINCE).days
_WEEKS = _SPAN_DAYS // 7 + 1


def _commit(day: int, added: int = 10, deleted: int = 0, email: str = "a@x") -> Commit:
    return Commit(
        sha=f"{day:040d}",
        author_name="Dev",
        author_email=email,
        timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(days=day),
        lines_added=added,
        lines_deleted=deleted,
    )


def _file(path: str, commits: int) -> FileStats:
    return FileStats(path=path, commits=commits, lines_added=10, lines_deleted=0)


def _profile(commits: list[Commit], files: list[FileStats]) -> dict[str, float]:
    return {a.name: a.value for a in repository_profile(commits, files, _SINCE, _UNTIL)}


def _expected(commits: list[Commit], files: list[FileStats]) -> dict[str, float | None]:
    return {a.name: a.expected for a in repository_profile(commits, files, _SINCE, _UNTIL)}


@pytest.mark.unit
class TestEveryAxisIsABoundedShare:
    """No axis may leave 0..1, whatever the input."""

    def test_all_axes_stay_within_range_on_extreme_input(self) -> None:
        commits = [_commit(d) for d in range(0, 400)]
        values = _profile(commits, [_file("a.py", 99)])
        assert values, "no axes produced"
        for name, value in values.items():
            assert 0.0 <= value <= 1.0, f"{name} left the range at {value}"

    def test_a_commit_outside_the_window_cannot_push_continuity_over_one(self) -> None:
        commits = [_commit(d) for d in range(0, 400)]
        assert _profile(commits, [])["Continuity"] <= 1.0

    def test_a_commit_outside_the_window_is_not_counted_as_recent(self) -> None:
        """`_recent_share` bounds its numerator by `until`, as `_continuity` does."""
        inside = [_commit(0)]
        outside = [_commit(0), _commit(_SPAN_DAYS + 40)]
        assert _profile(inside, [])["Recent work"] == _profile(outside, [])["Recent work"]


@pytest.mark.unit
class TestTheAxisOrderIsFixed:
    """A reader comparing two reports should find measures in the same places."""

    def test_order_matches_the_declared_contract(self) -> None:
        """Compared against a literal, not against `AXIS_ORDER`.

        `repository_profile` ends with `[ordered[name] for name in
        AXIS_ORDER]`, so asserting the returned order equals `AXIS_ORDER`
        compares the tuple with the thing built from it. It cannot fail.
        The contract is written out here independently, so changing the
        axis set is a deliberate act in two places.
        """
        contract = (
            "Continuity",
            "Recent work",
            "Shared",
            "Collaboration",
            "Revisiting",
            "Automation",
        )
        assert list(AXIS_ORDER) == list(contract), (
            "AXIS_ORDER changed; update this literal deliberately"
        )
        axes = repository_profile([_commit(1)], [], _SINCE, _UNTIL)
        assert [a.name for a in axes] == list(contract)

    def test_order_does_not_depend_on_the_values(self) -> None:
        low = repository_profile([_commit(1)], [], _SINCE, _UNTIL)
        high = repository_profile(
            [_commit(d) for d in range(0, _SPAN_DAYS)], [_file("a.py", 9)], _SINCE, _UNTIL
        )
        assert [a.name for a in low] == [a.name for a in high]


@pytest.mark.unit
class TestTheDroppedAxesStayDropped:
    """ADR 0012. Each restated a figure printed elsewhere in the report."""

    def test_spread_is_gone(self) -> None:
        """It was `1 - Gini/((n-1)/n)`, the Gini section's number again."""
        assert "Spread" not in AXIS_ORDER
        assert "Spread" not in _profile([_commit(1)], [])

    def test_small_steps_is_gone(self) -> None:
        """It was the first three change-size histogram buckets, summed."""
        assert "Small steps" not in AXIS_ORDER
        assert "Small steps" not in _profile([_commit(1)], [])

    def test_the_profile_cannot_see_contributors_at_all(self) -> None:
        """The profile takes commits, files and a window, never contributor rows.

        `Shared`, `Collaboration` and `Automation` read authors from the
        commits to count them (ADR 0016); there is still no ranked or scored
        contributor data to pass, and `TestItNamesNobody` holds the output.
        """
        import inspect

        parameters = list(inspect.signature(repository_profile).parameters)
        assert parameters == ["commits", "files", "since", "until"]


@pytest.mark.unit
class TestTheExtremesLandWhereTheDefinitionSays:
    """Each axis, driven to both ends of its range."""

    def test_a_commit_every_week_gives_full_continuity(self) -> None:
        commits = [_commit(d) for d in range(0, _SPAN_DAYS, 7)]
        assert _profile(commits, [])["Continuity"] == pytest.approx(1.0, abs=0.08)

    def test_one_commit_at_the_start_gives_almost_no_continuity(self) -> None:
        assert _profile([_commit(0)], [])["Continuity"] == pytest.approx(1 / _WEEKS)

    def test_all_work_in_the_final_quarter_gives_full_recent_work(self) -> None:
        commits = [_commit(d) for d in range(_SPAN_DAYS - 5, _SPAN_DAYS)]
        assert _profile(commits, [])["Recent work"] == 1.0

    def test_work_only_at_the_start_gives_no_recent_work(self) -> None:
        assert _profile([_commit(0), _commit(1)], [])["Recent work"] == 0.0

    def test_the_axis_is_not_degenerate_under_deterministic_windows(self) -> None:
        """The defect that retired the axis this one replaced.

        The old axis measured where the last commit sat in the window. Under
        `--deterministic` the window ends at the last commit, so it read 100%
        for every repository ever analysed.
        """
        commits = [_commit(d) for d in range(0, _SPAN_DAYS, 3)]
        assert _profile(commits, [])["Recent work"] < 0.5

    def test_files_touched_once_give_no_revisiting(self) -> None:
        assert _profile([_commit(1)], [_file("a.py", 1), _file("b.py", 1)])["Revisiting"] == 0.0

    def test_generated_files_do_not_count_towards_revisiting(self) -> None:
        files = [_file("poetry.lock", 40), _file("a.py", 1)]
        assert _profile([_commit(1)], files)["Revisiting"] == 0.0


@pytest.mark.unit
class TestTheExpectedValuesAreComputedNotChosen:
    """An expectation follows from the measure. A target is picked by a person.

    The distinction is the reason these exist at all: marking a value someone
    considered *good* would turn a description into a scorecard, which the
    module says it is not.
    """

    def test_continuity_expects_the_chance_a_week_is_hit(self) -> None:
        """One minus the chance every commit misses a given week."""
        commits = [_commit(d) for d in range(0, 20)]
        expected = _expected(commits, [])["Continuity"]
        assert expected == pytest.approx(1.0 - (1.0 - 1.0 / _WEEKS) ** 20)

    def test_continuity_expectation_rises_with_the_commit_count(self) -> None:
        """More commits, more weeks hit by chance -- so a high value means less."""
        few = _expected([_commit(d) for d in range(3)], [])["Continuity"]
        many = _expected([_commit(d) for d in range(60)], [])["Continuity"]
        assert few is not None and many is not None
        assert many > few

    def test_recent_work_expects_the_share_of_days_in_the_final_quarter(self) -> None:
        """Computed, not assumed to be 0.25: the cut-off is inclusive.

        The window is 89 days, so the quarter spans `89 // 4 + 1 = 23` of the
        90 days in it -- 0.2556, not 0.25. Assuming a quarter is a quarter
        would be wrong by a day.
        """
        expected = _expected([_commit(1)], [])["Recent work"]
        assert expected == pytest.approx((_SPAN_DAYS // 4 + 1) / (_SPAN_DAYS + 1))
        assert expected == pytest.approx(23 / 90)

    def test_revisiting_offers_no_expectation(self) -> None:
        """It would depend on repository age and file count, which it cannot see."""
        assert _expected([_commit(1)], [_file("a.py", 2)])["Revisiting"] is None

    def test_a_value_may_fall_either_side_of_its_expectation(self) -> None:
        """Proof that it is not a floor, a ceiling or a goal."""
        sparse = repository_profile([_commit(0), _commit(1)], [], _SINCE, _UNTIL)[0]
        regular = repository_profile(
            [_commit(d) for d in range(0, _SPAN_DAYS, 7)], [], _SINCE, _UNTIL
        )[0]
        assert sparse.name == regular.name == "Continuity"
        assert sparse.expected is not None and regular.expected is not None
        assert sparse.value < sparse.expected, "no case below expectation"
        assert regular.value > regular.expected, "no case above expectation"


@pytest.mark.unit
class TestItRefusesToProfileNothing:
    def test_no_commits_yields_no_axes(self) -> None:
        assert repository_profile([], [], _SINCE, _UNTIL) == []

    def test_a_zero_length_window_does_not_divide_by_zero(self) -> None:
        day = datetime.date(2026, 1, 1)
        axes = repository_profile([_commit(0)], [], day, day)
        assert [a.name for a in axes] == list(AXIS_ORDER)
        for axis in axes:
            assert 0.0 <= axis.value <= 1.0


@pytest.mark.unit
class TestItNamesNobody:
    def test_no_axis_carries_an_identity(self) -> None:
        commits = [_commit(1, email="alice@example.com")]
        axes = repository_profile(commits, [_file("a.py", 2)], _SINCE, _UNTIL)
        rendered = " ".join(f"{a.name} {a.description}" for a in axes)
        assert "alice" not in rendered
        assert "@" not in rendered


def _c(index: int, email: str, co: tuple[tuple[str, str], ...] = ()) -> Commit:
    return Commit(
        sha=f"{index:040d}",
        author_name=email.split("@")[0],
        author_email=email,
        timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        + datetime.timedelta(days=index),
        lines_added=1,
        lines_deleted=0,
        co_authors=co,
    )


@pytest.mark.unit
class TestTheNewMeasures:
    """ADR 0016: Shared, Collaboration and Automation, each a plain share."""

    def _axes(self, commits: list[Commit]) -> dict[str, object]:
        start = commits[0].timestamp.date()
        end = commits[-1].timestamp.date()
        return {a.name: a for a in repository_profile(commits, [], start, end)}

    def test_shared_is_the_commits_outside_the_busiest_author(self) -> None:
        commits = [_c(0, "a@e"), _c(1, "a@e"), _c(2, "a@e"), _c(3, "b@e")]
        shared = self._axes(commits)["Shared"]

        assert shared.value == pytest.approx(0.25)
        assert shared.expected == pytest.approx(0.5), "1 - 1/n for two authors"

    def test_shared_expects_one_minus_one_over_n(self) -> None:
        """Three people, where 1 - 1/n and 1/n differ; two could not tell them apart."""
        commits = [_c(0, "a@e"), _c(1, "a@e"), _c(2, "b@e"), _c(3, "c@e")]
        shared = self._axes(commits)["Shared"]

        assert shared.value == pytest.approx(0.5)
        assert shared.expected == pytest.approx(2 / 3)

    def test_a_bot_is_not_the_one_person(self) -> None:
        """Shared answers "is this one person?"; a busy bot is Automation's."""
        bot = "renovate[bot]@users.noreply.github.com"
        commits = [_c(i, bot) for i in range(8)] + [_c(8, "a@e"), _c(9, "b@e")]
        axes = self._axes(commits)

        assert axes["Shared"].value == pytest.approx(0.5)
        assert axes["Shared"].expected == pytest.approx(0.5)
        assert axes["Automation"].value == pytest.approx(0.8)

    def test_shared_without_people_has_no_expectation(self) -> None:
        bot = "dependabot[bot]@users.noreply.github.com"
        shared = self._axes([_c(0, bot), _c(1, bot)])["Shared"]

        assert shared.value == 0.0
        assert shared.expected is None

    def test_collaboration_counts_commits_with_a_co_author(self) -> None:
        commits = [_c(0, "a@e", (("H", "h@e"),)), _c(1, "a@e"), _c(2, "a@e"), _c(3, "a@e")]
        collaboration = self._axes(commits)["Collaboration"]

        assert collaboration.value == pytest.approx(0.25)
        assert collaboration.expected is None

    def test_automation_counts_bot_commits(self) -> None:
        commits = [_c(0, "a@e"), _c(1, "dependabot[bot]@users.noreply.github.com")]

        assert self._axes(commits)["Automation"].value == pytest.approx(0.5)
