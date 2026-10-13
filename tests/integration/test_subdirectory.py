# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Run from a subdirectory, a command reads the repository it belongs to, as Git does."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_WHO = {
    "GIT_AUTHOR_NAME": "Ana",
    "GIT_AUTHOR_EMAIL": "ana@e.test",
    "GIT_COMMITTER_NAME": "Ana",
    "GIT_COMMITTER_EMAIL": "ana@e.test",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        env={**os.environ, **_WHO},
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    (path / "src" / "deep").mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    for name in ("a.txt", "src/b.txt", "src/deep/c.txt"):
        (path / name).write_text(name, encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", name)
    _git(path, "tag", "v1", "HEAD~1")
    return path


def _json(*args: str) -> dict:
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "args",
    [("summary", "--deterministic"), ("state",), ("brief", "--from", "v1")],
)
def test_a_subdirectory_reads_the_whole_repository(repo: Path, args: tuple[str, ...]) -> None:
    from_root = _json(*args, "--repo", str(repo))
    from_sub = _json(*args, "--repo", str(repo / "src" / "deep"))

    assert from_sub == from_root


def test_the_working_directory_is_found_too(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo / "src")

    assert _json("state")["repository"]["name"] == "r"


def test_who_changed_takes_a_path_relative_to_where_it_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo / "src")

    result = CliRunner().invoke(app, ["who-changed", "deep", "--format", "json"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert json.loads(result.stdout)["path"] == "src/deep"


def test_generate_writes_the_report_at_the_repository_root(repo: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "--repo", str(repo / "src"), "-q"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert (repo / "reveille-report.html").is_file()
    assert not (repo / "src" / "reveille-report.html").exists()


def test_a_ceiling_directory_stops_the_search(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(repo))

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo / "src")])

    assert result.exit_code == ExitCode.CANNOT_RUN


def test_a_missing_directory_is_not_searched_from_elsewhere(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitPython runs Git in the current directory when the one given is missing."""
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(app, ["summary", "--repo", str(tmp_path / "missing")])

    assert result.exit_code == ExitCode.CANNOT_RUN
