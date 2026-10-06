"""Integration tests for the analysis window and the figures measured over it.

Every defect here was found by running the installed tool on real
repositories, and every one was invisible to the earlier tests because
their windows started and ended exactly on a commit day:

* a `--since` earlier than the first commit was counted as quiet time --
  "Longest quiet run 8,469 days" for a repository three years old;
* commits dated after today were counted in the totals while the header
  said the window ended today, and the timelines left them out;
* the quiet-run card and the quiet-run finding were computed by two
  functions with two definitions, so one page said 155 and 3;
* the dormancy finding could never appear, because it was measured against
  the last commit rather than the end of the window.

Dates are relative to today, so the repository keeps its shape whenever the
suite runs.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from reveille.config import ReportConfig
from reveille.services.report import generate_report

_TODAY = datetime.date.today()

# Days before today on which a commit lands. Twenty-one in a run, a gap of
# eight days (seven with no commit), then two more: enough commits for the
# cadence finding, and a last commit 100 days ago for the dormancy finding.
_OFFSETS = [*range(130, 109, -1), 102, 100]
_FIRST = _TODAY - datetime.timedelta(days=_OFFSETS[0])
_LAST = _TODAY - datetime.timedelta(days=_OFFSETS[-1])
_INTERNAL_QUIET_RUN = 7
_FUTURE = _TODAY + datetime.timedelta(days=400)


def _commit(repo: Path, index: int, day: datetime.date) -> None:
    stamp = f"{day.isoformat()}T12:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    (repo / f"f{index}.txt").write_text(f"{index}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"c{index}"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture(scope="module")
def dated_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Twenty-three commits ending 100 days ago, and one dated 400 days ahead."""
    repo = tmp_path_factory.mktemp("dated_repo")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for index, offset in enumerate(_OFFSETS):
        _commit(repo, index, _TODAY - datetime.timedelta(days=offset))
    _commit(repo, len(_OFFSETS), _FUTURE)
    return repo


def _json(repo: Path, out: Path, **kwargs: object) -> dict:
    config = ReportConfig(repo_path=repo, output_path=out, output_format="json", **kwargs)  # type: ignore[arg-type]
    return json.loads(generate_report(config)[0].read_text(encoding="utf-8"))


def _html(repo: Path, out: Path, **kwargs: object) -> str:
    config = ReportConfig(repo_path=repo, output_path=out, **kwargs)  # type: ignore[arg-type]
    return generate_report(config)[0].read_text(encoding="utf-8")


@pytest.mark.integration
class TestWindowStart:
    """A requested start before the first commit is not quiet time."""

    def test_starts_at_the_first_commit(self, dated_repo: Path, tmp_path: Path) -> None:
        early = _FIRST - datetime.timedelta(days=3000)
        payload = _json(dated_repo, tmp_path / "r.json", since=early)

        assert payload["metadata"]["analysis_since"] == _FIRST.isoformat()
        # What was asked for is still recorded, so nothing is hidden.
        assert payload["provenance"]["filters"]["requested_since"] == early.isoformat()

    def test_a_later_since_is_kept(self, dated_repo: Path, tmp_path: Path) -> None:
        later = _FIRST + datetime.timedelta(days=5)
        payload = _json(dated_repo, tmp_path / "r.json", since=later)

        assert payload["metadata"]["analysis_since"] == later.isoformat()


@pytest.mark.integration
class TestCommitsDatedAfterTheWindow:
    """One wrong clock must neither stretch the window nor be counted silently."""

    def test_are_left_out_of_every_figure(self, dated_repo: Path, tmp_path: Path) -> None:
        payload = _json(dated_repo, tmp_path / "r.json")

        assert payload["metadata"]["analysis_until"] == _TODAY.isoformat()
        assert payload["metadata"]["total_commits"] == len(_OFFSETS)
        assert sum(c["commit_count"] for c in payload["contributors"]) == len(_OFFSETS)

    def test_are_counted_in_provenance(self, dated_repo: Path, tmp_path: Path) -> None:
        payload = _json(dated_repo, tmp_path / "r.json")

        assert payload["provenance"]["commits_dated_after_window"] == 1

    def test_are_announced(self, dated_repo: Path, tmp_path: Path) -> None:
        notices: list[str] = []
        config = ReportConfig(repo_path=dated_repo, output_path=tmp_path / "r.html")
        generate_report(config, on_notice=notices.append)

        assert any("1 commit is dated after" in n and _TODAY.isoformat() in n for n in notices)

    def test_are_stated_in_the_report(self, dated_repo: Path, tmp_path: Path) -> None:
        text = " ".join(_html(dated_repo, tmp_path / "r.html").split())

        assert f"1 commit dated after {_TODAY.isoformat()} is not counted" in text

    def test_an_explicit_until_is_not_second_guessed(
        self, dated_repo: Path, tmp_path: Path
    ) -> None:
        payload = _json(dated_repo, tmp_path / "r.json", until=_FUTURE)

        assert payload["metadata"]["total_commits"] == len(_OFFSETS) + 1
        assert payload["provenance"]["commits_dated_after_window"] == 0

    def test_deterministic_mode_still_ends_on_the_last_commit(
        self, dated_repo: Path, tmp_path: Path
    ) -> None:
        """ADR 0008: a reproducible window closes on the repository, not the clock."""
        payload = _json(dated_repo, tmp_path / "r.json", deterministic=True)

        assert payload["metadata"]["analysis_until"] == _FUTURE.isoformat()
        assert payload["metadata"]["total_commits"] == len(_OFFSETS) + 1


def _card(html: str) -> int:
    match = re.search(r"Longest quiet run[^:<]*: ([\d,]+)", html)
    assert match, "the quiet-run card is missing"
    return int(match.group(1).replace(",", ""))


def _finding(html: str) -> int:
    match = re.search(r"longest quiet run of ([\d,]+) day", html)
    assert match, "the quiet-run finding is missing"
    return int(match.group(1).replace(",", ""))


@pytest.mark.integration
class TestOneQuietRun:
    """The card and the finding are one fact, so they must be one number."""

    def test_agree_with_a_lead_in_and_a_tail(self, dated_repo: Path, tmp_path: Path) -> None:
        early = _FIRST - datetime.timedelta(days=3000)
        html = _html(dated_repo, tmp_path / "r.html", since=early)

        assert _card(html) == _finding(html) == _INTERNAL_QUIET_RUN

    def test_agree_in_the_default_window(self, dated_repo: Path, tmp_path: Path) -> None:
        html = _html(dated_repo, tmp_path / "r.html")

        assert _card(html) == _finding(html) == _INTERNAL_QUIET_RUN

    def test_json_carries_the_same_number(self, dated_repo: Path, tmp_path: Path) -> None:
        payload = _json(dated_repo, tmp_path / "r.json")

        assert payload["derived"]["longest_inactive_streak"] == _INTERNAL_QUIET_RUN


@pytest.mark.integration
class TestDormancy:
    """The trailing silence is stated once, by the finding written for it."""

    def test_the_finding_appears(self, dated_repo: Path, tmp_path: Path) -> None:
        html = _html(dated_repo, tmp_path / "r.html")
        idle = (_TODAY - _LAST).days

        assert f"No commits in the last {idle} days." in html

    def test_not_in_deterministic_mode(self, dated_repo: Path, tmp_path: Path) -> None:
        """The window ends on the last commit there, so nothing has gone quiet."""
        html = _html(dated_repo, tmp_path / "r.html", deterministic=True)

        assert "No commits in the last" not in html


@pytest.mark.integration
def test_a_commit_made_today_is_counted_west_of_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timestamps are UTC; the cut-off was the local date. In a US evening
    the local date is a day behind UTC, and a commit made minutes earlier
    was announced as "dated after today" and left out. The zone below is
    chosen so the local date is always behind the UTC one."""
    import time

    now = datetime.datetime.now(datetime.UTC)
    today_utc = now.date()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    _commit(repo, 0, today_utc - datetime.timedelta(days=3))
    early_today = f"{today_utc.isoformat()}T00:00:30+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_AUTHOR_DATE": early_today,
        "GIT_COMMITTER_DATE": early_today,
    }
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "today"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    # POSIX offsets are west-positive: this zone is (hour + 1) hours behind UTC.
    monkeypatch.setenv("TZ", f"TST+{now.hour + 1}")
    time.tzset()
    try:
        assert datetime.date.today() < today_utc, "positive control: local date behind UTC"
        payload = _json(repo, tmp_path / "r.json")
    finally:
        monkeypatch.undo()
        time.tzset()

    assert payload["provenance"]["commits_dated_after_window"] == 0
    assert payload["metadata"]["total_commits"] == 2


@pytest.mark.integration
def test_a_left_out_commit_adds_nothing_to_the_file_figures(
    dated_repo: Path, tmp_path: Path
) -> None:
    """The commit dated 400 days ahead touched a file of its own."""
    from reveille.adapters.git_reader import GitReader

    reader = GitReader(dated_repo)
    reader.read_commits(
        branch="main", since=None, until=None, exclude_authors=[], dated_until=_TODAY
    )
    paths = {f.path for f in reader.file_stats}

    assert len(paths) == len(_OFFSETS), "positive control: every counted file is there"
    assert f"f{len(_OFFSETS)}.txt" not in paths


@pytest.mark.integration
def test_when_every_commit_is_after_the_window_the_error_says_so(tmp_path: Path) -> None:
    from reveille.adapters.git_reader import GitReader
    from reveille.exceptions import EmptyRepositoryError

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    _commit(repo, 0, _FUTURE)

    with pytest.raises(EmptyRepositoryError, match="1 commit is dated after"):
        GitReader(repo).read_commits(
            branch="main", since=None, until=None, exclude_authors=[], dated_until=_TODAY
        )
