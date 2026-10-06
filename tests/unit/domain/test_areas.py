# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Who changed each area, stated by fixed rules (ADR 0013)."""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.areas import ROOT_AREA, area_of, describe_areas, is_automated
from reveille.domain.models import AreaActivity

_END = datetime.date(2026, 10, 6)


def _area(
    name: str,
    commits: int,
    authors: set[str] | dict[str, datetime.date],
    last: datetime.date = _END,
) -> AreaActivity:
    dated = authors if isinstance(authors, dict) else dict.fromkeys(authors, last)
    return AreaActivity(area=name, commits=commits, last_changed=last, authors=dated)


@pytest.mark.unit
class TestAreaOf:
    @pytest.mark.parametrize(
        ("path", "depth", "area"),
        [
            ("src/reveille/adapters/renderer.py", 3, "src/reveille/adapters"),
            ("src/reveille/adapters/renderer.py", 2, "src/reveille"),
            ("src/reveille/cli.py", 3, "src/reveille"),
            ("docs/USER_GUIDE.md", 3, "docs"),
            ("README.md", 3, ROOT_AREA),
            ("a/b/c/d/e.py", 1, "a"),
        ],
    )
    def test_a_path_belongs_to_its_directory_cut_to_depth(
        self, path: str, depth: int, area: str
    ) -> None:
        assert area_of(path, depth) == area


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "email", "automated"),
    [
        ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com", True),
        ("renovate[bot]", "bot@renovateapp.com", True),
        ("Robert Bottomley", "bob@example.com", False),
    ],
)
def test_automation_is_a_stated_rule(name: str, email: str, automated: bool) -> None:
    assert is_automated(name, email) is automated


_NAMES = {
    "zoe@e.test": "Zoë Adams",
    "amir@e.test": "Amir Khan",
    "bea@e.test": "bea lopez",
    "bot@e.test": "dependabot[bot]",
}


@pytest.mark.unit
class TestDescribeAreas:
    def test_names_are_alphabetical_with_no_date_or_count_per_person(self) -> None:
        (statement,) = describe_areas(
            [_area("src/x", 12, {"zoe@e.test", "amir@e.test", "bea@e.test"})],
            _NAMES,
            set(_NAMES),
            _END,
        )

        assert statement.headline == "12 commits by 3 authors."
        assert statement.authors == "Authors: Amir Khan, bea lopez and Zoë Adams."
        assert statement.evidence == "last changed 2026-10-06"

    def test_automation_is_counted_and_listed_apart(self) -> None:
        (statement,) = describe_areas(
            [_area("deps", 4, {"bot@e.test", "amir@e.test"})], _NAMES, set(_NAMES), _END
        )

        assert statement.headline == "4 commits by 1 author and 1 automated account."
        assert statement.authors == "Authors: Amir Khan."
        assert statement.automated == "Automated: dependabot[bot]."

    def test_an_author_below_the_threshold_is_counted_not_named(self) -> None:
        (statement,) = describe_areas(
            [_area("src/x", 5, {"zoe@e.test", "amir@e.test"})],
            _NAMES,
            {"amir@e.test"},
            _END,
        )

        assert statement.headline == "5 commits by 2 authors."
        assert "Zoë" not in statement.authors
        assert statement.authors == "Authors: Amir Khan. 1 below --min-commits is not named."

    def test_a_long_list_shows_the_five_most_recent_alphabetically(self) -> None:
        """Alphabetical-first-five of 783 names was a list of arbitrary
        handles. The five shown are the most recent, ordered by name, with
        no date beside any of them."""
        last = {f"p{i}@e.test": _END - datetime.timedelta(days=i) for i in range(8)}
        names = {e: f"Person {chr(ord('H') - int(e[1]))}" for e in last}
        (statement,) = describe_areas([_area("src/x", 30, last)], names, set(last), _END)

        assert statement.authors == (
            "Authors include Person D, Person E, Person F, Person G and Person H, "
            "the five to change it most recently, and 3 others."
        )
        assert "2026" not in statement.authors

    def test_a_one_person_repository_does_not_repeat_the_qualification(self) -> None:
        names = {"amir@e.test": "Amir Khan", "bot@e.test": "dependabot[bot]"}
        statements = describe_areas(
            [_area("src/x", 9, {"amir@e.test"}), _area("docs", 3, {"amir@e.test"})],
            names,
            set(names),
            _END,
        )

        assert not any("maintainer" in n for s in statements for n in s.notes)

    def test_a_one_author_area_is_qualified(self) -> None:
        (statement,) = describe_areas(
            [_area("src/x", 9, {"amir@e.test", "bot@e.test"})], _NAMES, set(_NAMES), _END
        )

        assert any("One committer is not one maintainer" in n for n in statement.notes)

    def test_a_quiet_area_is_stated_against_the_window_end(self) -> None:
        last = _END - datetime.timedelta(days=45)
        (statement,) = describe_areas(
            [_area("docs", 3, {"amir@e.test", "zoe@e.test"}, last)], _NAMES, set(_NAMES), _END
        )

        assert "Not changed in the last 45 days of the window." in statement.notes

    def test_the_most_changed_eight_are_shown(self) -> None:
        areas = [_area(f"a{i:02d}", i + 1, {"amir@e.test"}) for i in range(12)]
        shown = describe_areas(areas, _NAMES, set(_NAMES), _END)

        assert [s.area for s in shown] == [f"a{i:02d}" for i in range(11, 3, -1)]

    def test_no_statement_characterises_a_person(self) -> None:
        """The words ADR 0013 rules out, in any statement."""
        areas = [
            _area("src/x", 12, {"zoe@e.test", "amir@e.test"}),
            _area("docs", 2, {"amir@e.test"}, _END - datetime.timedelta(days=60)),
        ]
        for statement in describe_areas(areas, _NAMES, set(_NAMES), _END):
            text = " ".join(
                [statement.headline, statement.authors, statement.automated, *statement.notes]
            ).lower()
            for word in ("mainly", "owner", "owns", "expert", "%", "most active", "top"):
                assert word not in text, f"{word!r} in {text!r}"


@pytest.mark.unit
def test_an_automated_account_below_the_threshold_is_counted_too() -> None:
    (statement,) = describe_areas(
        [_area("deps", 3, {"bot@e.test", "amir@e.test"})], _NAMES, {"amir@e.test"}, _END
    )

    assert statement.automated == ""
    assert statement.not_listed == 1
    assert statement.authors == "Authors: Amir Khan. 1 below --min-commits is not named."
