# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A date at either end of the calendar is an answer or a clear refusal, not a defect."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    repo = tmp_path / "ws" / "r"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
    )
    return tmp_path / "ws"


def test_a_window_ending_at_the_first_day_is_read(workspace: Path) -> None:
    result = CliRunner().invoke(app, ["repos", str(workspace), "--until", "0001-01-01"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "defect" not in result.stderr


def test_a_configured_end_on_the_last_day_is_refused(workspace: Path) -> None:
    config = workspace / "c.toml"
    config.write_text("[report]\nuntil = 9999-12-31\n", encoding="utf-8")
    out = workspace / "r.html"

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(workspace / "r"), "-c", str(config), "-o", str(out), "-q"]
    )

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "must be before 9999-12-31" in result.stderr, result.stderr


def _commits(repo: Path, *window: str) -> tuple[int, int]:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--format", "json", *window])
    if result.exit_code != ExitCode.SUCCESS:
        return result.exit_code, 0
    return result.exit_code, int(json.loads(result.stdout)["totals"]["commits"])


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (("--until", "2150-01-01"), (ExitCode.SUCCESS, 1)),
        (("--until", "9999-12-30"), (ExitCode.SUCCESS, 1)),
        (("--since", "1900-01-01"), (ExitCode.SUCCESS, 1)),
        (("--since", "0001-01-01"), (ExitCode.SUCCESS, 1)),
        (("--since", "2150-01-01"), (ExitCode.NEGATIVE, 0)),
        (("--since", "9999-12-30"), (ExitCode.NEGATIVE, 0)),
        (("--until", "1969-12-31"), (ExitCode.NEGATIVE, 0)),
    ],
)
def test_a_date_git_cannot_parse_gives_the_answer_the_window_means(
    workspace: Path, window: tuple[str, ...], expected: tuple[int, int]
) -> None:
    """Git reads an ISO date only from 1970 to 2099; past 2099 `--before` matched nothing."""
    assert _commits(workspace / "r") == (ExitCode.SUCCESS, 1), "positive control"

    assert _commits(workspace / "r", *window) == expected


def test_a_commit_in_the_last_week_of_the_calendar_is_drawn(tmp_path: Path) -> None:
    """Git accepts 9999-12-31; the week after it cannot be held, and the HTML failed to render."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    last_day = {
        "GIT_AUTHOR_DATE": "@253402214400 +0000",
        "GIT_COMMITTER_DATE": "@253402214400 +0000",
    }
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
        env={**os.environ, **last_day},
    )
    out = tmp_path / "r.html"

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--deterministic", "-o", str(out), "-q"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "9999-12-27" in out.read_text(encoding="utf-8")


def _commit_dated(repo: Path, when: str, message: str) -> None:
    """Commit dated `when` (UTC), written raw: Git's date parser stops at 2099."""
    import datetime

    stamp = int(datetime.datetime.fromisoformat(f"{when}T12:00:00+00:00").timestamp())
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    body = (
        f"tree {tree}\nparent {parent}\nauthor A <a@e.test> {stamp} +0000\n"
        f"committer A <a@e.test> {stamp} +0000\n\n{message}\n\nCo-authored-by: Bea <b@e.test>\n"
    )
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
        cwd=repo,
        input=body,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/heads/main", sha], cwd=repo, check=True)


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (("--until", "2099-12-31"), 1),
        (("--until", "2150-01-01"), 1),
        (("--until", "2150-06-01"), 2),
        (("--since", "2100-01-01", "--until", "2200-01-01"), 1),
        (("--since", "2150-06-02", "--until", "2200-01-01"), 0),
        (("--since", "2100-01-01", "--until", "2150-05-31"), 0),
    ],
)
def test_a_commit_dated_past_2099_is_bounded_by_the_window(
    workspace: Path, window: tuple[str, ...], expected: int
) -> None:
    """Past 2099 Git's bound was dropped (`--until`) or moved to 2099 (`--since`)."""
    _commit_dated(workspace / "r", "2150-06-01", "far")

    code, commits = _commits(workspace / "r", *window)

    assert code == (ExitCode.SUCCESS if expected else ExitCode.NEGATIVE)
    assert commits == expected


def test_a_co_author_past_the_window_is_not_credited(workspace: Path) -> None:
    _commit_dated(workspace / "r", "2150-06-01", "far")

    result = CliRunner().invoke(
        app,
        ["summary", "--repo", str(workspace / "r"), "--format", "json", "--until", "2099-12-31"],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert json.loads(result.stdout)["totals"]["commits_with_co_authors"] == 0
