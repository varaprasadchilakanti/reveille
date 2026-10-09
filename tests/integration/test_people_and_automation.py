"""The distribution figures count people; automated accounts are stated (ADR 0017).

Ana makes six commits, Ben two and `dependabot[bot]` eight. Counted as a
person, the bot is the busiest "contributor", the one who "holds half the
commits", and the Gini describes three accounts; the profile beside those
figures already left it out of Shared. Each test below fails if the bot is
put back into the population or left unstated.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.domain.concentration import gini_coefficient

_BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


def _make(path: Path, authors: list[tuple[str, str]]) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day, (name, email) in enumerate(authors, start=1):
        (path / "a.txt").write_text(f"{day}\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    return path


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    ana, ben = ("Ana", "ana@e.test"), ("Ben", "ben@e.test")
    return _make(tmp_path_factory.mktemp("people") / "repo", [ana] * 6 + [ben] * 2 + [_BOT] * 8)


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def _invoke(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.mark.integration
class TestTheFiguresDescribePeople:
    def test_the_json_states_both_populations(self, repo: Path) -> None:
        payload = json.loads(
            _invoke(
                "generate", "--repo", str(repo), "--format", "json", "--deterministic", "-o", "-"
            )
        )
        derived = payload["derived"]

        assert payload["metadata"]["total_commits"] == 16, "every commit is still counted"
        assert derived["population_size"] == 3
        assert (derived["people"], derived["automated_accounts"], derived["automated_commits"]) == (
            2,
            1,
            8,
        )
        assert derived["gini_coefficient"] == round(gini_coefficient([6, 2]), 2)
        assert derived["commit_concentration"] == 1, "Ana alone holds half of the people's commits"

    def test_the_table_still_lists_the_account(self, repo: Path) -> None:
        payload = json.loads(
            _invoke(
                "generate", "--repo", str(repo), "--format", "json", "--deterministic", "-o", "-"
            )
        )

        assert _BOT[0] in {c["name"] for c in payload["contributors"]}

    def test_the_report_counts_two_people_and_says_what_it_left_out(self, repo: Path) -> None:
        text = _text(_invoke("generate", "--repo", str(repo), "--deterministic", "-o", "-"))

        assert "Contributors: 2 " in text
        assert "1 automated account (8 commits) is counted in the commit and line totals" in text
        assert "most concentrated 2 people can be" in text
        assert "distributed across 2 contributors" in text

    def test_the_summary_counts_authors_and_states_the_account(self, repo: Path) -> None:
        out = _invoke("summary", "--repo", str(repo), "--deterministic")

        assert "16 commits by 2 authors and 1 automated account;" in out


@pytest.mark.integration
class TestTheEdges:
    def test_without_automated_accounts_nothing_is_stated(self, tmp_path: Path) -> None:
        repo = _make(tmp_path / "r", [("Ana", "ana@e.test"), ("Ben", "ben@e.test")])
        html = _invoke("generate", "--repo", str(repo), "--deterministic", "-o", "-")

        assert 'class="cards-note"' not in html

    def test_a_repository_of_automated_accounts_has_no_people(self, tmp_path: Path) -> None:
        repo = _make(tmp_path / "r", [_BOT, _BOT, ("renovate[bot]", "bot@e.test")])
        text = _text(_invoke("generate", "--repo", str(repo), "--deterministic", "-o", "-"))

        assert "Contributors: 0 " in text
        assert "2 automated accounts (3 commits) are counted" in text
        assert "With no people there is no distribution to measure" in text
