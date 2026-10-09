"""Replace refs are not honoured: the report describes the objects it names (ADR 0018).

A replace ref substituted a copy of the only commit, authored by "Mallory",
for the real one authored by "Ana". The report named Mallory while its
provenance recorded the hash of Ana's commit.
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


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, env=env, input=stdin, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    path = tmp_path_factory.mktemp("replace") / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "c")
    real = _git(path, "rev-parse", "HEAD")
    forged = _git(path, "cat-file", "commit", real).replace(
        "author Ana <ana@e.test>", "author Mallory <m@e.test>"
    )
    substitute = _git(path, "hash-object", "-t", "commit", "-w", "--stdin", stdin=forged + "\n")
    _git(path, "replace", real, substitute)
    # Guard the guard: plain Git now shows the substitute.
    assert _git(path, "log", "-1", "--format=%an") == "Mallory"
    return path, real


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.mark.integration
def test_the_report_names_the_author_of_the_commit_it_records(repo: tuple[Path, str]) -> None:
    path, real = repo
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(path), "--format", "json", "--deterministic", "-o", "-"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    payload = json.loads(result.stdout)

    assert payload["provenance"]["head_sha"] == real
    assert [c["name"] for c in payload["contributors"]] == ["Ana"]


@pytest.mark.integration
def test_who_changed_reads_the_same_objects(repo: tuple[Path, str]) -> None:
    path, _ = repo
    result = CliRunner().invoke(
        app, ["who-changed", "a.txt", "--repo", str(path), "--format", "json"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr

    assert [a["name"] for a in json.loads(result.stdout)["authors"]["list"]] == ["Ana"]


@pytest.mark.integration
def test_a_graft_file_is_not_followed(tmp_path: Path) -> None:
    """`.git/info/grafts` rewrites parents too, and GIT_NO_REPLACE_OBJECTS does
    not cover it: with it obeyed, three commits read as two."""
    path = tmp_path / "grafted"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    for day in (1, 2, 3):
        (path / "a.txt").write_text(f"{day}\n", encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", f"c{day}")
    (path / ".git" / "info").mkdir(exist_ok=True)
    (path / ".git" / "info" / "grafts").write_text(
        _git(path, "rev-parse", "HEAD~1") + "\n", encoding="utf-8"
    )
    assert _git(path, "rev-list", "--count", "HEAD") == "2", "guard the guard"

    result = CliRunner().invoke(app, ["summary", "--repo", str(path), "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    document = json.loads(result.stdout)

    assert document["totals"]["commits"] == 3
    # And it is stated. Detection once asked Git where the graft file is,
    # while every read points Git at the null device for it: never found.
    assert document["repository"]["graft_file_not_followed"] is True
    assert "a .git/info/grafts file, which `git log` follows" in result.stderr


@pytest.mark.integration
def test_what_was_not_followed_is_stated(repo: tuple[Path, str]) -> None:
    """`git log` follows the replace ref, so a reader comparing needs to know."""
    path, _ = repo
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(path), "--format", "json", "--deterministic", "-o", "-"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    provenance = json.loads(result.stdout)["provenance"]

    assert provenance["replace_refs_not_followed"] == 1
    assert provenance["graft_file_not_followed"] is False
    assert "This repository has 1 replace ref, which `git log` follows" in result.stderr

    html = CliRunner().invoke(app, ["generate", "--repo", str(path), "-o", "-"]).stdout
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    assert "Not followed: 1 replace ref, which git log follows" in text


@pytest.mark.integration
def test_an_ordinary_repository_states_nothing(tmp_path: Path) -> None:
    path = tmp_path / "plain"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "c")

    result = CliRunner().invoke(app, ["summary", "--repo", str(path), "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    repository = json.loads(result.stdout)["repository"]

    assert (repository["replace_refs_not_followed"], repository["graft_file_not_followed"]) == (
        0,
        False,
    )
    assert "follows and Reveille does not" not in result.stderr
