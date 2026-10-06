# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`min_commits` filters the listing, not the analysis.

The defect these guard against was measurable in one command. On a
repository split 238/84 between two contributors, `--min-commits 100`
reported `gini_coefficient: 0.00` -- perfect equality -- because the
contributor who made the split uneven had been removed from the
population before the Gini was computed. Meanwhile `total_commits`
stayed at 322, so the suppressed contributor's exact commit count was a
subtraction away, with nothing in the report saying why the numbers
disagreed.

`--exclude-author` behaved differently again: it recomputed the total.
Two filters that read as interchangeable had two disclosure behaviours.

See ADR 0011. The decision is that a filter chooses who is listed, and
every figure describes the whole repository, with the difference stated.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from reveille.config import ReportConfig
from reveille.services.report import generate_report


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _repo_with_two_contributors(root: Path, major: int, minor: int) -> Path:
    """Build a repository where one contributor is far busier than the other.

    Args:
        root: Directory to create the repository in.
        major: Commits authored by the busier contributor.
        minor: Commits authored by the quieter one.

    Returns:
        The repository path.
    """
    root.mkdir(parents=True)
    _run(["git", "init", "-q", "-b", "main"], root)
    _run(["git", "config", "commit.gpgsign", "false"], root)
    # No background housekeeping: see `_init_repo` in test_security.py.
    _run(["git", "config", "maintenance.auto", "false"], root)
    _run(["git", "config", "gc.auto", "0"], root)
    for index in range(major + minor):
        busy = index < major
        name, email = ("Major", "major@example.com") if busy else ("Minor", "minor@example.com")
        (root / f"f{index}.txt").write_text(f"{index}\n")
        _run(["git", "add", "-A"], root)
        _run(
            [
                "git",
                "-c",
                f"user.name={name}",
                "-c",
                f"user.email={email}",
                "commit",
                "-q",
                "-m",
                f"add f{index}",
            ],
            root,
        )
    return root


def _derived(repo: Path, out: Path, min_commits: int) -> dict[str, object]:
    """Generate JSON output and return its `derived` block."""
    generate_report(
        ReportConfig(
            repo_path=repo,
            output_path=out,
            output_format="json",
            min_commits=min_commits,
            deterministic=True,
        )
    )
    payload = json.loads(out.read_text())
    assert isinstance(payload, dict)
    derived = payload["derived"]
    assert isinstance(derived, dict)
    derived["_total_commits"] = payload["metadata"]["total_commits"]
    derived["_listed"] = payload["metadata"]["unique_contributors"]
    derived["_rows"] = sum(c["commit_count"] for c in payload["contributors"])
    return derived


class TestFiltersDoNotChangeTheFigures:
    """The same repository yields the same distribution, filtered or not."""

    def test_min_commits_leaves_the_derived_figures_alone(self, tmp_path: Path) -> None:
        """This is the whole decision, in one assertion.

        Before: unfiltered 0.24, filtered 0.00. The filter changed the
        answer to a question about the repository.
        """
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)

        unfiltered = _derived(repo, tmp_path / "all.json", min_commits=1)
        filtered = _derived(repo, tmp_path / "some.json", min_commits=5)

        assert filtered["_listed"] == 1, "the filter did not suppress anybody; nothing is tested"
        assert unfiltered["_listed"] == 2
        assert filtered["gini_coefficient"] == unfiltered["gini_coefficient"]
        assert filtered["commit_concentration"] == unfiltered["commit_concentration"]
        assert filtered["population_size"] == unfiltered["population_size"] == 2

    def test_the_suppressed_contributor_is_counted_and_declared(self, tmp_path: Path) -> None:
        """The rows will not sum to the total, so the report says why."""
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        filtered = _derived(repo, tmp_path / "some.json", min_commits=5)

        assert filtered["_total_commits"] == 12
        assert filtered["_rows"] == 9
        assert filtered["contributors_below_threshold"] == 1, (
            "the gap between rows and total is undeclared, which is the defect"
        )

    def test_no_threshold_declares_nobody_suppressed(self, tmp_path: Path) -> None:
        """A report with no filter must not imply one."""
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        unfiltered = _derived(repo, tmp_path / "all.json", min_commits=1)

        assert unfiltered["contributors_below_threshold"] == 0
        assert unfiltered["_rows"] == unfiltered["_total_commits"] == 12


class TestEveryRepositoryLevelFigureUsesTheSamePopulation:
    """ADR 0011 applied to the charts, not only to the printed figures.

    The first pass at ADR 0011 fixed `_compute_derived_stats` and missed
    `_build_charts`. The result was a report that contradicted itself: with
    `--min-commits 100` over a two-contributor repository it printed a Gini of
    0.25 over two contributors, a Lorenz specification of `null`, and a profile
    axis of 0.0 described as "one contributor, so there is nothing to spread".

    Nothing failed. Correcting the profile's population was measured against
    the whole suite and changed no result, because the guards read prose and
    JSON keys and the profile axes are in neither. These are those guards.
    """

    def _profile(self, repo: Path, out: Path, min_commits: int) -> dict[str, float]:
        """Render and return the profile axes, by name."""
        generate_report(
            ReportConfig(
                repo_path=repo,
                output_path=out,
                min_commits=min_commits,
                deterministic=True,
            )
        )
        html = out.read_text(encoding="utf-8")
        table = html[html.index('<table class="profile">') :]
        table = table[: table.index("</table>")]
        rows = re.findall(
            r'<th scope="row" class="profile-name">\s*([^<]+?)\s*<.*?'
            r'class="profile-value">(\d+)%<',
            table,
            re.DOTALL,
        )
        assert rows, "the report carries no profile table"
        return {name: float(value) for name, value in rows}

    def test_min_commits_does_not_change_the_profile(self, tmp_path: Path) -> None:
        """Now guaranteed by construction, and still asserted end to end.

        `Spread` was the only axis that read contributor data, and it was
        removed at 0.9.0 (ADR 0012), so `repository_profile` no longer takes a
        contributor argument at all. A listing filter therefore cannot reach
        the profile even in principle. This stays because the property the
        reader cares about is about the rendered report, not about a
        signature: a future axis that did read people would fail here.
        """
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        unfiltered = self._profile(repo, tmp_path / "all.html", 1)
        filtered = self._profile(repo, tmp_path / "some.html", 5)

        assert unfiltered, "no profile rendered; this would pass whatever happened"
        assert filtered == unfiltered, (
            "a filter changed what the profile is about, not just who is listed"
        )

    def test_min_commits_does_not_remove_the_lorenz_curve(self, tmp_path: Path) -> None:
        """The curve describes the repository, so a listing filter cannot empty it."""
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        out = tmp_path / "filtered.html"
        generate_report(
            ReportConfig(repo_path=repo, output_path=out, min_commits=5, deterministic=True)
        )
        spec = re.search(
            r'id="spec-lorenz">(.*?)</script>', out.read_text(encoding="utf-8"), re.DOTALL
        )
        assert spec is not None
        assert spec.group(1).strip() != "null", (
            "the Lorenz curve went empty under a listing filter, while its Gini "
            "still printed beside it"
        )

    def test_the_profile_does_not_claim_a_lone_contributor(self, tmp_path: Path) -> None:
        """The exact sentence that shipped, so its return is noticed."""
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        out = tmp_path / "filtered.html"
        generate_report(
            ReportConfig(repo_path=repo, output_path=out, min_commits=5, deterministic=True)
        )
        assert "nothing to spread" not in out.read_text(encoding="utf-8")


class TestTheReportSaysWhichPopulationItDescribes:
    """A number whose population is left to inference is not disclosed."""

    def test_the_html_states_what_was_held_back(self, tmp_path: Path) -> None:
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        out = tmp_path / "report.html"
        generate_report(
            ReportConfig(
                repo_path=repo,
                output_path=out,
                min_commits=5,
                deterministic=True,
            )
        )
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out.read_text(encoding="utf-8")))

        assert "Listing: 1 of 2 contributors" in text
        assert "below the min-commits threshold of 5" in text
        assert "still counted in every figure here" in text

    def test_an_unfiltered_html_report_claims_no_suppression(self, tmp_path: Path) -> None:
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        out = tmp_path / "report.html"
        generate_report(ReportConfig(repo_path=repo, output_path=out, deterministic=True))
        text = out.read_text(encoding="utf-8")

        assert "min-commits threshold" not in text

    def test_a_lone_contributor_is_not_given_a_range_of_zero(self, tmp_path: Path) -> None:
        """The degenerate caption used to contradict itself.

        At one contributor the Gini ceiling is (1-1)/1 = 0, and the
        sentence rendered as "Gini runs 0 (even) to 0.00, which is the
        most concentrated 1 contributors can be" -- a vacuous range and a
        grammatical error, in shipped output.
        """
        repo = _repo_with_two_contributors(tmp_path / "repo", major=6, minor=0)
        out = tmp_path / "report.html"
        generate_report(ReportConfig(repo_path=repo, output_path=out, deterministic=True))
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out.read_text(encoding="utf-8")))

        assert "1 contributors can be" not in text
        assert "Gini runs 0 (even) to 0.00" not in text
        assert "With a single contributor there is no distribution to measure" in text

    def test_one_listed_contributor_is_not_mistaken_for_one_contributor(
        self,
        tmp_path: Path,
    ) -> None:
        """The distinction the whole decision rests on, asserted directly.

        A filter can leave exactly one row in the table while the
        repository still has two contributors. The caption must describe
        the population, not the row count -- otherwise a report over a
        two-person repository claims there is no distribution to measure,
        having just computed one.

        This case was missing when the guards above were first written. It
        was found by breaking the property and watching nothing fail:
        every other test here uses a repository whose listed count and
        population happen to agree.
        """
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        out = tmp_path / "report.html"
        generate_report(
            ReportConfig(
                repo_path=repo,
                output_path=out,
                min_commits=5,
                deterministic=True,
            )
        )
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out.read_text(encoding="utf-8")))

        assert "most concentrated 2 contributors can be" in text
        assert "With a single contributor" not in text


@pytest.mark.parametrize("threshold", [1, 2, 5, 100])
def test_the_population_is_the_repository_at_every_threshold(
    tmp_path: Path,
    threshold: int,
) -> None:
    """Whatever is listed, the figures are about all twelve commits."""
    repo = _repo_with_two_contributors(tmp_path / f"repo{threshold}", major=9, minor=3)
    derived = _derived(repo, tmp_path / f"out{threshold}.json", min_commits=threshold)

    assert derived["_total_commits"] == 12
    assert derived["population_size"] == 2
    assert derived["gini_coefficient"] == 0.25


class TestTheContributorsCardCountsThePopulation:
    """The card describes the repository, like every figure beside it.

    With `--min-commits 999` it read "Contributors 0" next to "1 hold half
    the commits": it counted the rows the threshold left in the table, while
    every other card counted the contributors the figures are about.
    """

    def test_a_threshold_does_not_change_the_card(self, tmp_path: Path) -> None:
        repo = _repo_with_two_contributors(tmp_path / "repo", major=9, minor=3)
        out = tmp_path / "r.html"
        generate_report(
            ReportConfig(repo_path=repo, output_path=out, min_commits=999, deterministic=True)
        )
        html = out.read_text(encoding="utf-8")

        assert "Contributors: 2</span>" in html
        assert "0 of 2 contributors" in " ".join(html.split()), "positive control"
