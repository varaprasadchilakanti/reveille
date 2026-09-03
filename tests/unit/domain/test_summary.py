# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The written summary, which must state only what the numbers support.

Prose is the easiest place in a report to overclaim, so the properties
asserted here are mostly about what the generator refuses to say: it
names no one, it judges no one, and it withholds a finding rather than
compute one from a sample too small to carry it.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.models import Commit, ContributorStats
from reveille.domain.summary import Finding, summarise

_START = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC)


def _commits(count: int, *, every_days: int = 1, email: str = "a@example.com") -> list[Commit]:
    return [
        Commit(
            sha=f"{index:040d}",
            author_name="Ada Lovelace",
            author_email=email,
            timestamp=_START + datetime.timedelta(days=index * every_days),
            lines_added=10,
            lines_deleted=1,
        )
        for index in range(count)
    ]


def _stats(counts: list[int]) -> list[ContributorStats]:
    return [
        ContributorStats(
            name=f"Contributor {index}",
            email=f"c{index}@example.com",
            commit_count=count,
            lines_added=10,
            lines_deleted=1,
            active_days=count,
            first_commit_date=_START.date(),
            last_commit_date=_START.date() + datetime.timedelta(days=30),
        )
        for index, count in enumerate(counts)
    ]


def _text(findings: list[Finding]) -> str:
    return " ".join(f"{f.headline} {f.detail} {f.evidence}" for f in findings)


@pytest.mark.unit
class TestItNamesNobody:
    """ADR 0010: the report must not assess individuals. Prose included."""

    def test_no_contributor_name_or_address_appears(self) -> None:
        findings = summarise(_commits(60), _stats([50, 8, 2]))
        assert findings
        body = _text(findings)
        for stat in _stats([50, 8, 2]):
            assert stat.name not in body
            assert stat.email not in body
        assert "Ada Lovelace" not in body

    def test_no_evaluative_vocabulary(self) -> None:
        """A finding states what the history shows, not what it is worth."""
        forbidden = (
            "healthy",
            "unhealthy",
            "good",
            "bad",
            "poor",
            "excellent",
            "concerning",
            "worrying",
            "risk",
            "productive",
            "unproductive",
            "should",
            "must improve",
            "underperform",
        )
        body = _text(summarise(_commits(60), _stats([50, 8, 2]))).lower()
        found = [word for word in forbidden if word in body]
        assert found == [], f"the summary passes judgement: {found}"


@pytest.mark.unit
class TestItWithholdsWhatItCannotSupport:
    """A statistic over a handful of commits is arithmetic, not evidence."""

    def test_no_findings_at_all_for_an_empty_history(self) -> None:
        assert summarise([], []) == []

    def test_cadence_is_withheld_below_the_minimum(self) -> None:
        findings = summarise(_commits(5), _stats([5]))
        assert not any("between active days" in f.headline for f in findings)

    def test_cadence_appears_once_there_is_enough(self) -> None:
        findings = summarise(_commits(40), _stats([40]))
        assert any("between active days" in f.headline for f in findings)

    def test_distribution_is_withheld_for_a_single_contributor(self) -> None:
        findings = summarise(_commits(40), _stats([40]))
        assert not any("contributor" in f.headline for f in findings if "commits" in f.headline)


@pytest.mark.unit
class TestTheDistributionSentenceMatchesTheNumbers:
    """The wording once contradicted its own evidence."""

    def test_an_even_split_is_not_called_a_majority(self) -> None:
        """`[5, 5]` is exactly even; 50% is not "one contributor authored"."""
        findings = summarise(_commits(40), _stats([20, 20]))
        headline = next(f.headline for f in findings if "contributor" in f.headline)
        assert "no single majority" in headline, headline

    def test_a_dominant_share_is_stated_plainly(self) -> None:
        findings = summarise(_commits(40), _stats([202, 78]))
        headline = next(f.headline for f in findings if "contributor" in f.headline)
        assert "72%" in headline or "73%" in headline

    def test_two_contributors_never_read_as_evenly_spread_at_seventy_percent(
        self,
    ) -> None:
        """The Gini is bounded by (n-1)/n, so a raw threshold misreads small n.

        With two contributors the coefficient cannot exceed 0.50 however
        lopsided the split, which once produced "spread fairly evenly...
        the busiest holding 73%" in a single sentence.
        """
        findings = summarise(_commits(40), _stats([202, 78]))
        headline = next(f.headline for f in findings if "contributor" in f.headline)
        assert "evenly" not in headline.lower()

    def test_concentration_carries_the_bus_factor_caveat(self) -> None:
        findings = summarise(_commits(40), _stats([200, 5, 5]))
        detail = next(f.detail for f in findings if "authored" in f.headline)
        assert "not a bus factor" in detail


@pytest.mark.unit
class TestItIsReproducible:
    """`--deterministic` promises byte-identical output. Prose is output."""

    def test_the_same_history_produces_the_same_sentences(self) -> None:
        first = summarise(_commits(60), _stats([50, 8, 2]))
        second = summarise(_commits(60), _stats([50, 8, 2]))
        assert first == second

    def test_recency_defaults_to_the_history_rather_than_the_clock(self) -> None:
        """Reading the wall clock would make two runs of one commit differ."""
        commits = _commits(40)
        assert summarise(commits, _stats([40])) == summarise(commits, _stats([40]))
        dormant = summarise(commits, _stats([40]), today=datetime.date(2030, 1, 1))
        assert any("No commits in the last" in f.headline for f in dormant)
        assert not any(
            "No commits in the last" in f.headline for f in summarise(commits, _stats([40]))
        )


@pytest.mark.unit
class TestEveryFindingCarriesItsEvidence:
    """A sentence a reader cannot check against a chart is an assertion."""

    def test_evidence_is_always_present_and_non_empty(self) -> None:
        for finding in summarise(_commits(60), _stats([50, 8, 2])):
            assert finding.evidence.strip(), f"no evidence for: {finding.headline}"

    def test_merge_exclusion_is_stated_where_the_count_is(self) -> None:
        """Counts here are lower than raw `git log`, and that must be said."""
        span = summarise(_commits(60), _stats([60]))[0]
        assert "Merge commits are excluded" in span.detail
