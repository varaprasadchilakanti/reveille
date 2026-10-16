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


@pytest.fixture(scope="module")
def forged(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A victim's ordinary commit, then an attacker's commit whose author name
    carries whole forged records reusing the victim's real commit hash."""
    path = tmp_path_factory.mktemp("forged") / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "b.txt").write_text("b\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=Bystander", "-c", "user.email=by@e.test", "commit", "-qm", "b")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=Victim", "-c", "user.email=victim@e.test", "commit", "-qm", "v")
    victim = _git(path, "rev-parse", "HEAD")
    forged_record = f"\x1e{victim}\x1fMallory\x1fmallory@e.test\x1f1788000000\x1f{victim}"
    name = f"Eve\x1feve@e.test\x1f1788000000{forged_record * 3}\x1e{victim}\x1fMallory"
    tree, parent = _git(path, "write-tree"), victim
    crafted = (
        f"tree {tree}\nparent {parent}\n"
        f"author {name} <eve@e.test> 1700000000 +0000\n"
        "committer Eve <eve@e.test> 1700000000 +0000\n\nforge\n"
    )
    sha = _git(path, "hash-object", "-t", "commit", "-w", "--literally", "--stdin", stdin=crafted)
    _git(path, "update-ref", "refs/heads/main", sha)
    assert _git(path, "rev-list", "--count", "HEAD") == "3", "guard the guard"
    return path, victim


@pytest.mark.integration
def test_forged_records_add_no_commit_and_no_person(forged: tuple[Path, str]) -> None:
    """Git sees 3 commits by 3 people. The forged records reuse the victim's hash,
    so neither copy can be trusted: both the forging commit and the victim's are
    counted as unreadable and stated, and no forged person appears."""
    path, _ = forged
    result = CliRunner().invoke(app, ["summary", "--repo", str(path), "--format", "json"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    payload = json.loads(result.stdout)
    assert payload["totals"]["commits"] == 1
    assert payload["repository"]["commits_unreadable"] == 2
    assert "could not be read" in result.stderr
    assert "mallory" not in (result.stdout + result.stderr).lower()


@pytest.mark.integration
def test_no_commit_is_credited_to_the_forged_person(forged: tuple[Path, str]) -> None:
    path, _ = forged
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(path), "--format", "json", "--output", "-"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    emails = {c["email"] for c in json.loads(result.stdout)["contributors"]}
    assert emails == {"by@e.test"}


@pytest.mark.integration
def test_a_commit_with_an_unusable_date_is_counted_and_said(tmp_path: Path) -> None:
    """Year 10000 passes fsck but no datetime holds it; it was dropped without a word."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "ordinary")
    tree, parent = _git(path, "write-tree"), _git(path, "rev-parse", "HEAD")
    crafted = (
        f"tree {tree}\nparent {parent}\n"
        "author Hidden <h@e.test> 253402300800 +0000\n"
        "committer Hidden <h@e.test> 253402300800 +0000\n\nfar future\n"
    )
    sha = _git(path, "hash-object", "-t", "commit", "-w", "--literally", "--stdin", stdin=crafted)
    _git(path, "update-ref", "refs/heads/main", sha)

    result = CliRunner().invoke(app, ["summary", "--repo", str(path), "--format", "json"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    payload = json.loads(result.stdout)
    assert payload["repository"]["commits_unreadable"] == 1
    assert "could not be read" in result.stderr
