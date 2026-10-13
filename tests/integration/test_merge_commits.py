"""Merge commits are left out of every figure (ADR 0001).

The report says so on every page, so a regression here would make it say
something false. Each test runs the real command over a real repository
holding a merge whose only author never made an ordinary commit, and whose
merge commit edits a file of its own: if a merge were read, that author
would be counted, listed or named, and the commit total would rise.

Two reads carry the exclusion, `git log` and the `git rev-list` whose
hashes authenticate each log record, so removing `--no-merges` from one
alone changes nothing; these tests fail when it is removed from both. Line
counts are not asserted: `git log --numstat` prints no diff for a merge,
so such a test would pass with merges read.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


def _git(
    repo: Path, *args: str, name: str = "Ana", email: str = "ana@e.test", day: int = 1
) -> None:
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
    subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True)


def _write(repo: Path, file: str, text: str) -> None:
    (repo / file).write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three ordinary commits by two people, then a merge by a third.

    The merge is made with `--no-ff --no-commit` and an extra edit before it
    is committed, so it carries a change of its own to `merged.txt`, which
    no ordinary commit touches: a path query would find it only by reading
    the merge.
    """
    repo = tmp_path_factory.mktemp("merges") / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "a.txt", "1\n")
    _git(repo, "add", "-A", day=1)
    _git(repo, "commit", "-qm", "a", day=1)

    _git(repo, "switch", "-q", "-c", "feature", day=2)
    _write(repo, "b.txt", "2\n")
    _git(repo, "add", "-A", name="Ben", email="ben@e.test", day=2)
    _git(repo, "commit", "-qm", "b", name="Ben", email="ben@e.test", day=2)

    _git(repo, "switch", "-q", "main", day=3)
    _write(repo, "a.txt", "1\n3\n")
    _git(repo, "add", "-A", day=3)
    _git(repo, "commit", "-qm", "c", day=3)

    merger = {"name": "Mo Merger", "email": "mo@e.test", "day": 4}
    _git(repo, "merge", "-q", "--no-ff", "--no-commit", "feature", **merger)  # type: ignore[arg-type]
    _write(repo, "merged.txt", "only the merge wrote this\n" * 40)
    _git(repo, "add", "-A", **merger)  # type: ignore[arg-type]
    _git(repo, "commit", "-qm", "Merge feature", **merger)  # type: ignore[arg-type]
    return repo


def _run(*args: str) -> dict:
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run from an empty directory, so nothing can land in the working tree."""
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def test_the_fixture_really_holds_a_merge(repo: Path) -> None:
    """Guard the guard: without a merge commit every test below is vacuous."""
    merges = subprocess.run(
        ["git", "rev-list", "--merges", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    total = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    assert (merges, total) == ("1", "4")


@pytest.mark.integration
class TestMergeCommitsAreExcluded:
    def test_the_full_report_counts_three_commits_and_two_people(self, repo: Path) -> None:
        payload = _run("generate", "--repo", str(repo), "--deterministic", "-o", "-")

        assert payload["metadata"]["total_commits"] == 3
        assert sorted(c["email"] for c in payload["contributors"]) == ["ana@e.test", "ben@e.test"]

    def test_the_summary_counts_three_commits_and_two_authors(self, repo: Path) -> None:
        payload = _run("summary", "--repo", str(repo))

        assert payload["totals"] == {
            "commits": 3,
            "authors": 2,
            "automated_accounts": 0,
            "commits_with_co_authors": 0,
        }

    def test_a_file_only_a_merge_touched_has_no_history(self, repo: Path) -> None:
        result = CliRunner().invoke(
            app, ["who-changed", "merged.txt", "--repo", str(repo), "--format", "json"]
        )

        assert result.exit_code == ExitCode.NEGATIVE, result.stdout
        assert "Mo Merger" not in result.stdout


@pytest.mark.integration
class TestTheExclusionIsStated:
    """Counts are lower than `git log`'s by the merges; the output says by how many."""

    def test_provenance_counts_the_merges_left_out(self, repo: Path) -> None:
        payload = _run("generate", "--repo", str(repo), "--deterministic", "-o", "-")

        assert payload["provenance"]["merge_commits_excluded"] == 1

    def test_the_summary_counts_them_too(self, repo: Path) -> None:
        payload = _run("summary", "--repo", str(repo))

        assert payload["repository"]["merge_commits_excluded"] == 1

    def test_only_merges_in_the_window_are_counted(self, repo: Path) -> None:
        payload = _run("summary", "--repo", str(repo), "--until", "2026-03-03")

        assert payload["repository"]["merge_commits_excluded"] == 0

    def test_the_summary_text_says_so(self, repo: Path) -> None:
        result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

        assert "1 merge commit is not counted" in result.stdout


@pytest.mark.integration
def test_the_merge_count_ignores_exclude_author(repo: Path) -> None:
    """Documented: merges in the range, whoever made them."""
    payload = _run("summary", "--repo", str(repo), "--exclude-author", "mo@e.test")

    assert payload["repository"]["merge_commits_excluded"] == 1
