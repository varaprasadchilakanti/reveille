# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`hide_emails` leaves no address in the data any renderer is handed.

Checked on the dataset, not on one output: a field no renderer prints today is
one a later output could print.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    AreaActivity,
    CoAuthor,
    Commit,
    ContributorStats,
    RankedContributor,
    ReportData,
    RepositoryMetadata,
)
from reveille.domain.pseudonyms import hide_emails

pytestmark = pytest.mark.unit

_DAY = datetime.date(2026, 3, 1)
_WHEN = datetime.datetime(2026, 3, 1, 10, tzinfo=datetime.UTC)


def _stats(name: str, email: str) -> ContributorStats:
    return ContributorStats(
        name=name,
        email=email,
        commit_count=1,
        lines_added=1,
        lines_deleted=0,
        active_days=1,
        first_commit_date=_DAY,
        last_commit_date=_DAY,
    )


def _data() -> ReportData:
    listed = _stats("Ana", "ana@corp.test")
    return ReportData(
        metadata=RepositoryMetadata(
            name="r",
            remote_url="ssh://jane@git.corp.test/team/r.git",
            analysed_branch="main",
            total_commits=2,
            unique_contributors=2,
            analysis_since=_DAY,
            analysis_until=_DAY,
            generated_at=_WHEN,
        ),
        provenance=AnalysisProvenance(
            reveille_version="0.0.0-test",
            schema_version=SCHEMA_VERSION,
            head_sha=None,
            requested_branch=None,
            requested_since=None,
            requested_until=None,
            exclude_authors_count=0,
            min_commits=2,
            ranking_enabled=False,
            ranking_weights=None,
            mailmap_applied=False,
            deterministic=True,
        ),
        ranked_contributors=[RankedContributor(listed, 0.0, 0.0, 1, "")],
        commits=[
            Commit("a" * 40, "Ana", "ana@corp.test", _WHEN, 1, 0, (("Carol", "carol@corp.test"),)),
            Commit("b" * 40, "ben@corp.test", "ben@corp.test", _WHEN, 1, 0),
        ],
        suppressed_contributors=[_stats("ben@corp.test", "ben@corp.test")],
        areas=[AreaActivity("src", 2, _DAY, {"ana@corp.test": _DAY, "ben@corp.test": _DAY})],
        co_authors_only=[CoAuthor("Carol", "carol@corp.test", 1)],
    )


def test_no_address_is_left_in_any_field() -> None:
    hidden = repr(hide_emails(_data()))

    for address in ("ana@corp.test", "ben@corp.test", "carol@corp.test", "jane@"):
        assert address not in hidden, address


def test_the_positive_control_holds_every_address() -> None:
    plain = repr(_data())

    for address in ("ana@corp.test", "ben@corp.test", "carol@corp.test", "jane@"):
        assert address in plain, address


def test_one_address_has_one_token_everywhere() -> None:
    hidden = hide_emails(_data())

    ben = hidden.suppressed_contributors[0].email
    assert hidden.commits[1].author_email == ben
    assert ben in hidden.areas[0].authors
    assert hidden.co_authors_only[0].email == hidden.commits[0].co_authors[0][1]


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("jane@git.corp.test:team/r.git", "git.corp.test:team/r.git"),
        ("ssh://jane@git.corp.test/team/r.git", "ssh://git.corp.test/team/r.git"),
        ("https://git.corp.test/team/r.git", "https://git.corp.test/team/r.git"),
    ],
)
def test_a_remote_loses_only_its_login(remote: str, expected: str) -> None:
    data = _data()
    data.metadata = RepositoryMetadata(**{**data.metadata.__dict__, "remote_url": remote})

    assert hide_emails(data).metadata.remote_url == expected


def test_a_bot_suffix_after_an_address_in_a_name_survives() -> None:
    data = _data()
    data.ranked_contributors = [
        RankedContributor(_stats("ci@builds.test[bot]", "ci@builds.test"), 0.0, 0.0, 1, "")
    ]

    stats = hide_emails(data).ranked_contributors[0].stats
    assert stats.name == "(address hidden)[bot]"
    assert stats.email.endswith("[bot]@hidden.invalid")
