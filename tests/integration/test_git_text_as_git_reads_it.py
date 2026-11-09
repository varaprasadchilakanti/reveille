# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Text Git hands over is split and read as Git reads it.

Python's `str.splitlines` also breaks at U+2028, U+0085, form feed and `\\x1c`-`\\x1e`; Git
breaks only at a line feed. Each test pairs Reveille's reading with Git's own.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from reveille.adapters.git_reader import GitReader
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str, name: str = "Ana", email: str = "ana@e.test") -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "C",
        "GIT_COMMITTER_EMAIL": "c@e.test",
    }
    done = subprocess.run(
        ["git", *args], cwd=repo, check=True, env=env, capture_output=True, text=True
    )
    return done.stdout


def _commit(repo: Path, message: str, name: str = "Ana", email: str = "ana@e.test") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message, name=name, email=email)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "base")
    return path


def _json(repo: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", "json", "-o", "-", *args]
    )
    return result.exit_code, json.loads(result.stdout) if result.exit_code == 0 else {}


def test_a_path_that_is_not_utf8_reads_with_quote_path_off(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / os.fsdecode(b"d\xff\xfe")).write_text("x\n", encoding="utf-8")
    _commit(repo, "odd name")
    settings = tmp_path / "global.cfg"
    settings.write_text("[core]\n\tquotePath = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
    # Positive control: with the setting, Git prints the raw byte.
    assert (
        b"\xff"
        in subprocess.run(
            ["git", "log", "--numstat", "--format="], cwd=repo, check=True, capture_output=True
        ).stdout
    )

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "-o", str(repo / "r.html")])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr


def test_a_mailmap_line_git_reads_as_a_comment_maps_no_one(repo: Path) -> None:
    (repo / "b").write_text("1\n", encoding="utf-8")
    _commit(repo, "victim", name="Vic", email="v@e.test")
    (repo / ".mailmap").write_text(
        "# aliases\u2028Mallory <m@e.test> <v@e.test>\n", encoding="utf-8"
    )
    _commit(repo, "mailmap")
    # Positive control: Git maps the address to itself.
    assert _git(repo, "check-mailmap", "<v@e.test>").strip() == "<v@e.test>"

    code, document = _json(repo)

    assert code == ExitCode.SUCCESS
    emails = {person["email"] for person in document["contributors"]}
    assert "v@e.test" in emails
    assert "m@e.test" not in emails


def test_a_mailmap_with_crlf_line_ends_still_maps(repo: Path) -> None:
    (repo / "b").write_text("1\n", encoding="utf-8")
    _commit(repo, "old address", name="Vic", email="old@e.test")
    (repo / ".mailmap").write_bytes(b"Vic <v@e.test> <old@e.test>\r\n")
    _commit(repo, "mailmap")
    assert _git(repo, "check-mailmap", "<old@e.test>").strip() == "Vic <v@e.test>"

    code, document = _json(repo)

    assert code == ExitCode.SUCCESS
    assert "v@e.test" in {person["email"] for person in document["contributors"]}


def test_no_readable_commit_cannot_run(tmp_path: Path) -> None:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "only", name="Ana\x1eX")
    # Positive control: Git kept the separator in the author name.
    assert "\x1e" in _git(path, "log", "--format=%an")

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(path), "--format", "json", "-o", "-"]
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "1 commit in the window could not be read" in result.stderr


def test_a_filter_that_leaves_only_unreadable_commits_cannot_run(tmp_path: Path) -> None:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "readable")
    (path / "a").write_text("2\n", encoding="utf-8")
    _commit(path, "unreadable", name="Bo\x1eX")

    result = CliRunner().invoke(
        app,
        [
            *("generate", "--repo", str(path), "--format", "json", "-o", "-"),
            *("--exclude-author", "ana@e.test"),
        ],
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "No commit was counted" in result.stderr
    assert "Try removing an --exclude-author value." in result.stderr


def test_an_exclusion_is_not_a_branch(repo: Path) -> None:
    # Positive control: Git accepts it as a revision.
    assert _git(repo, "rev-parse", "--verify", "^main").startswith("^")

    code, _ = _json(repo, "--branch", "^main")

    assert code == ExitCode.CANNOT_RUN


def test_an_excluded_path_keeps_its_leading_space(repo: Path) -> None:
    for directory, name, email in ((" sp", "Spa", "spa@e.test"), ("sp", "Bob", "bob@e.test")):
        (repo / directory).mkdir()
        (repo / directory / "f").write_text("1\n", encoding="utf-8")
        _commit(repo, directory, name=name, email=email)

    code, document = _json(repo, "--exclude-path", " sp")

    assert code == ExitCode.SUCCESS
    emails = {person["email"] for person in document["contributors"]}
    assert "spa@e.test" not in emails
    assert "bob@e.test" in emails


def test_an_unmatched_path_is_quoted_so_its_spaces_show(repo: Path) -> None:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--exclude-path", "a "])

    assert result.exit_code == ExitCode.SUCCESS
    assert "'a '" in result.stderr


def test_a_branch_name_with_an_odd_space_is_one_branch(repo: Path) -> None:
    _git(repo, "branch", "feature\u00a0one")
    _git(repo, "branch", "a\u2028b")
    _git(repo, "branch", "a\u2028c")

    state = GitReader(repo).read_state()

    assert state.branches == 4
    assert state.branches_merged == 4


def test_a_tag_name_with_a_line_separator_is_listed_whole(repo: Path) -> None:
    (repo / "a").write_text("2\n", encoding="utf-8")
    _commit(repo, "second")
    _git(repo, "tag", "v1\u2028rc")

    tags = GitReader(repo).tags_in_range(branch=None, from_commit=None, since=None, until=None)

    assert tags == ["v1\u2028rc"]


@pytest.mark.xfail(strict=True, reason="TODO(git-read): numstat without -z prints both alike")
def test_a_directory_named_like_a_rename_is_its_own_path(repo: Path) -> None:
    (repo / "x => src").mkdir()
    (repo / "x => src" / "main.py").write_text("1\n2\n", encoding="utf-8")
    _commit(repo, "arrow")

    reader = GitReader(repo)
    reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])

    assert "x => src/main.py" in {stats.path for stats in reader.file_stats}
