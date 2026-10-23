# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The `Next:` command a brief prints reads the same history when run as printed.

It dropped `--repo`, `--branch` and the exclusions: run from where the first
brief was, it said "is not a valid Git repository", and after `--branch feature`
it read `main`. And a history of empty commits printed "Most changed areas: "
with nothing after it.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _commit(repo: Path, who: str, name: str | None, day: str) -> None:
    if name is not None:
        (repo / name).write_text(name, encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=repo, check=True)
    when = f"{day}T12:00:00Z"
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", who],
        cwd=repo,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": who,
            "GIT_AUTHOR_EMAIL": f"{who.lower()}@e.test",
            "GIT_COMMITTER_NAME": who,
            "GIT_COMMITTER_EMAIL": f"{who.lower()}@e.test",
            "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_DATE": when,
        },
    )


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`work/` to run from, `work/my repo/` holding `main` and a longer `feature`."""
    repo = tmp_path / "work" / "my repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    _commit(repo, "Ana", "a.txt", "2026-09-01")
    subprocess.run(["git", "switch", "-q", "-c", "feature"], cwd=repo, check=True)
    _commit(repo, "Bob", "b.txt", "2026-09-02")
    subprocess.run(["git", "switch", "-q", "main"], cwd=repo, check=True)
    monkeypatch.chdir(tmp_path / "work")
    return repo


def _next(output: str) -> list[str]:
    [hint] = re.findall(r"^Next: `?(reveille [^`\n]+)`?$", output, re.MULTILINE)
    return shlex.split(hint)[1:]


@pytest.mark.parametrize("output_format", ["text", "markdown"])
def test_the_next_brief_runs_where_the_first_did(layout: Path, output_format: str) -> None:
    asked = ["--since", "2026-08-01", "--branch", "feature", "--exclude-author", "Ana"]
    first = CliRunner().invoke(
        app, ["brief", "--repo", "my repo", *asked, "--format", output_format]
    )
    assert first.exit_code == ExitCode.SUCCESS, first.stderr

    following = _next(first.stdout)
    assert following[:2] == ["brief", "--from"]
    assert following[following.index("--repo") + 1] == "my repo"
    assert following[following.index("--branch") + 1] == "feature"
    assert following[following.index("--exclude-author") + 1] == "Ana"

    _commit(layout, "Cy", None, "2026-09-03")  # on main: the next brief must not see it
    second = CliRunner().invoke(app, [*following, "--format", "json"])
    assert second.exit_code == ExitCode.NEGATIVE, second.stdout
    assert "No commits" in second.stderr or "no commits" in second.stderr.lower()


def test_a_brief_from_here_suggests_no_options(
    layout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(layout)
    first = CliRunner().invoke(app, ["brief", "--since", "2026-08-01"])
    assert first.exit_code == ExitCode.SUCCESS, first.stderr

    assert _next(first.stdout)[:2] == ["brief", "--from"]
    assert len(_next(first.stdout)) == 3


@pytest.mark.parametrize(
    ("output_format", "areas", "types"),
    [
        ("text", "Most changed areas: none.", "File changes by type: none."),
        ("markdown", "- **Most changed areas:** none", "- **File changes by type:** none"),
    ],
)
def test_an_empty_list_says_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_format: str, areas: str, types: str
) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    _commit(tmp_path, "Ana", None, "2026-09-01")
    _commit(tmp_path, "Ana", None, "2026-09-02")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["brief", "--since", "2026-08-01", "--format", output_format])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    lines = result.stdout.splitlines()
    assert areas in lines
    assert types in lines
