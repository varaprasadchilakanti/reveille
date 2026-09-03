# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Charts key on a display name, which is not unique.

ADR 0002 makes the lowercased email the identity key. Two contributors
can share a display name -- two different people, or one person under
two addresses before a `.mailmap` ties them together -- and Plotly then
resolves the repeated label differently per trace type: a bar chart
collapses the bars onto one category, a pie sums the slices, a line
chart draws two legend entries nobody can tell apart.

Measured against this repository before its `.mailmap` existed: the
table said 201 and 1, the bar chart said 201, the pie said 202. Three
views of one repository, three answers.

A `.mailmap` fixes that for one person under two addresses. It is the
wrong tool for two genuinely different people who happen to share a
name, and most repositories have no `.mailmap` at all -- so the charts
have to be right without one.
"""

from __future__ import annotations

import datetime
import json

import pytest

from reveille.adapters.renderer import (
    _build_commit_share_pie,
    _build_contributor_commits_chart,
    _build_contributor_lines_chart,
    _build_contributor_timeline_chart,
    _build_lines_share_pie,
    _contributor_labels,
)
from reveille.domain.models import Commit, ContributorStats, RankedContributor


def _ranked(name: str, email: str, commits: int) -> RankedContributor:
    return RankedContributor(
        stats=ContributorStats(
            name=name,
            email=email,
            commit_count=commits,
            lines_added=commits * 10,
            lines_deleted=commits,
            active_days=1,
            first_commit_date=datetime.date(2024, 1, 1),
            last_commit_date=datetime.date(2024, 1, 2),
        ),
        composite_score=float(commits),
        percentile=50.0,
        tier=1,
        tier_designation="Private",
    )


#: Two different people sharing a display name, plus a third contributor.
COLLIDING = [
    _ranked("Alex Chen", "alex.chen@corp.example", 120),
    _ranked("Dana Ray", "dana@corp.example", 60),
    _ranked("Alex Chen", "achen@other.example", 20),
]

DISTINCT = [
    _ranked("Alex Chen", "alex.chen@corp.example", 120),
    _ranked("Dana Ray", "dana@corp.example", 60),
]


@pytest.mark.unit
class TestTheLabelMap:
    """One label per identity, and no clutter where there is no ambiguity."""

    def test_a_colliding_name_carries_its_address(self) -> None:
        labels = _contributor_labels(COLLIDING)
        assert labels["alex.chen@corp.example"] == "Alex Chen <alex.chen@corp.example>"
        assert labels["achen@other.example"] == "Alex Chen <achen@other.example>"

    def test_an_uncontested_name_is_left_alone(self) -> None:
        """Disambiguating everything would clutter the common case."""
        assert _contributor_labels(COLLIDING)["dana@corp.example"] == "Dana Ray"
        assert set(_contributor_labels(DISTINCT).values()) == {"Alex Chen", "Dana Ray"}

    def test_every_label_is_unique(self) -> None:
        labels = _contributor_labels(COLLIDING)
        assert len(set(labels.values())) == len(COLLIDING)

    def test_the_map_is_keyed_on_the_identity_key(self) -> None:
        """ADR 0002: lowercased email. Mixed case must not split a person."""
        mixed = [_ranked("Alex Chen", "Alex.Chen@Corp.Example", 5)]
        assert "alex.chen@corp.example" in _contributor_labels(mixed)


@pytest.mark.unit
class TestNoChartCollapsesTwoContributorsIntoOne:
    """The failure was silent and differed per trace type."""

    def test_the_commits_bar_chart_draws_one_bar_each(self) -> None:
        trace = json.loads(_build_contributor_commits_chart(COLLIDING))["data"][0]
        assert len(set(trace["y"])) == len(COLLIDING), (
            f"{len(set(trace['y']))} categories for {len(COLLIDING)} contributors: "
            "two bars are being drawn over each other"
        )
        assert sum(trace["x"]) == 200

    def test_the_lines_bar_chart_draws_one_group_each(self) -> None:
        figure = json.loads(_build_contributor_lines_chart(COLLIDING))
        for trace in figure["data"]:
            assert len(set(trace["x"])) == len(COLLIDING)

    @pytest.mark.parametrize(
        ("builder", "total"),
        [(_build_commit_share_pie, 200), (_build_lines_share_pie, 200 * 11)],
    )
    def test_a_pie_does_not_sum_two_people_into_one_slice(
        self, builder: object, total: int
    ) -> None:
        trace = json.loads(builder(COLLIDING))["data"][0]  # type: ignore[operator]
        assert len(set(trace["labels"])) == len(COLLIDING), (
            "two slices share a label, so Plotly adds them together and the "
            "pie disagrees with the table beside it"
        )
        assert sum(trace["values"]) == total, "aggregation lost or invented data"

    def test_the_timeline_legend_entries_are_distinguishable(self) -> None:
        commits = [
            Commit(
                sha=f"{index:040d}",
                author_name=contributor.stats.name,
                author_email=contributor.stats.email,
                timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
                + datetime.timedelta(days=index),
                lines_added=1,
                lines_deleted=0,
            )
            for index, contributor in enumerate(COLLIDING)
        ]
        figure = json.loads(_build_contributor_timeline_chart(commits, COLLIDING))
        names = [trace["name"] for trace in figure["data"]]
        assert len(set(names)) == len(names), (
            f"the legend shows {names}: two entries a reader cannot tell apart"
        )


@pytest.mark.unit
class TestTheCommonCaseIsUnchanged:
    """A guard that cries wolf gets weakened by whoever hits it next."""

    @pytest.mark.parametrize(
        "builder",
        [
            _build_contributor_commits_chart,
            _build_commit_share_pie,
            _build_lines_share_pie,
        ],
    )
    def test_no_address_is_shown_when_names_are_unique(self, builder: object) -> None:
        emitted = builder(DISTINCT)  # type: ignore[operator]
        assert "@" not in emitted, "an address is being shown where nothing is ambiguous"


@pytest.mark.unit
class TestOneIdentityHasOneLabelEverywhere:
    """The report draws the same person in several places.

    The timeline legend shows only the top `_MAX_SERIES` contributors,
    while the heatmap's contributor menu lists every one of them. If each
    built its own label map from the subset it happens to draw, the same
    address would appear as `Alex Chen` in one and `Alex Chen <...>` in
    the other -- and a reader would have no way to know they are the same
    person. A name is ambiguous relative to the whole report, not
    relative to whichever slice a chart shows.
    """

    def test_a_collision_across_the_series_cap_labels_consistently(self) -> None:
        from reveille.adapters.renderer import _MAX_SERIES, _build_heatmap_data

        contributors = [
            _ranked(f"Person {index}", f"p{index}@example.com", 100 - index)
            for index in range(_MAX_SERIES)
        ]
        # A second "Person 0", ranked last, so it falls outside the cap.
        contributors.append(_ranked("Person 0", "other@example.com", 1))

        commits = [
            Commit(
                sha=f"{index:040d}",
                author_name=contributor.stats.name,
                author_email=contributor.stats.email,
                timestamp=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
                + datetime.timedelta(days=index),
                lines_added=1,
                lines_deleted=0,
            )
            for index, contributor in enumerate(contributors)
        ]

        figure = json.loads(_build_contributor_timeline_chart(commits, contributors))
        drawn = {trace["name"] for trace in figure["data"]}

        heatmap = json.loads(
            _build_heatmap_data(
                commits,
                contributors,
                datetime.date(2024, 1, 1),
                datetime.date(2024, 12, 31),
            )
        )
        menu = {entry["name"] for entry in heatmap["contributors"]}

        expected = _contributor_labels(contributors)["p0@example.com"]
        assert "@" in expected, "the collision should have forced disambiguation"
        assert expected in drawn, (
            f"the timeline legend shows {drawn}, not the report-wide label "
            f"{expected!r}: it built its map from the contributors it draws"
        )
        assert expected in menu, f"the heatmap menu shows {menu}, disagreeing with the legend"
