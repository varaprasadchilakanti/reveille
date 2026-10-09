"""A commit the read cannot parse is counted and stated, never lost (ADR 0019).

An author field carrying the record separator splits its log record, and the
fragments fail the shape check: that is the defence against a forged record.
Before 0.9.0 the commit then vanished without a word, so the report held one
commit fewer than the branch and said nothing.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Ana", "-c", "user.email=ana@e.test", *args],
        cwd=repo,
        check=True,
        input=stdin,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("unreadable") / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "ordinary")
    tree, parent = _git(path, "write-tree"), _git(path, "rev-parse", "HEAD")
    crafted = (
        f"tree {tree}\nparent {parent}\n"
        "author Ev\x1eil <e@e.test> 1700000000 +0000\n"
        "committer Ev <e@e.test> 1700000000 +0000\n\ncrafted\n"
    )
    sha = _git(path, "hash-object", "-t", "commit", "-w", "--literally", "--stdin", stdin=crafted)
    _git(path, "update-ref", "refs/heads/main", sha)
    assert _git(path, "rev-list", "--count", "HEAD") == "2", "guard the guard"
    return path


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.mark.integration
def test_the_summary_counts_it_and_says_so(repo: Path) -> None:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    document = json.loads(result.stdout)

    assert document["totals"]["commits"] == 1
    assert document["repository"]["commits_unreadable"] == 1
    assert "1 commit could not be read and is not counted" in result.stderr


@pytest.mark.integration
def test_the_report_header_states_it(repo: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "-o", "-"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", result.stdout))

    assert "Not read: 1 commit could not be read" in text


@pytest.mark.integration
def test_an_ordinary_history_reports_none(tmp_path: Path) -> None:
    path = tmp_path / "plain"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "c")

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(path), "--format", "json", "-o", "-"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr

    assert json.loads(result.stdout)["provenance"]["commits_unreadable"] == 0
