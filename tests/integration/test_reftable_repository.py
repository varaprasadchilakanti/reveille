# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A repository whose refs are in reftable format is read like any other.

Git 2.45 can store refs in reftable files, leaving `.git/HEAD` naming a
placeholder branch and no ref files at all. A reader of ref files finds no
commits there, which is the negative answer, exit 1, for a repository with
history.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "ws" / "r"
    path.mkdir(parents=True)
    made = subprocess.run(
        ["git", "init", "-q", "--ref-format=reftable", "-b", "main"],
        cwd=path,
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("this Git cannot make a reftable repository")
    for n in range(3):
        (path / "f.txt").write_text(str(n), encoding="utf-8")
        _git(path, "add", "f.txt")
        _git(path, "commit", "-qm", f"c{n}")
    _git(path, "tag", "v1", "HEAD~1")
    assert not (path / ".git" / "refs" / "heads" / "main").exists(), "positive control"
    return path


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


def test_every_reader_counts_its_commits(repo: Path) -> None:
    for args, field in (
        (["summary"], ("totals", "commits")),
        (["brief"], ("totals", "commits")),
        (["brief", "--from", "HEAD~2"], ("totals", "commits")),
        (["who-changed", "f.txt"], ("commits",)),
    ):
        code, out, err = _run(*args, "--repo", str(repo), "--format", "json")
        assert code == ExitCode.SUCCESS, (args, err)
        answer = json.loads(out)
        for key in field:
            answer = answer[key]
        assert answer == (1 if args == ["brief"] else 2 if len(args) == 3 else 3), args


def test_the_report_and_state_name_the_tip(repo: Path) -> None:
    tip = _git(repo, "rev-parse", "HEAD")

    code, out, err = _run("generate", "-q", "--repo", str(repo), "--format", "json", "-o", "-")
    assert code == ExitCode.SUCCESS, err
    assert json.loads(out)["provenance"]["head_sha"] == tip

    code, out, err = _run("state", "--repo", str(repo), "--format", "json")
    assert code == ExitCode.SUCCESS, err
    assert json.loads(out)["head"] == tip


def test_a_workspace_holding_one_is_read_whole(repo: Path) -> None:
    code, out, err = _run("repos", str(repo.parent), "--format", "json")

    assert code == ExitCode.SUCCESS, err
    [row] = json.loads(out)["repositories"]
    assert row["status"] == "active" and row["commits"] == 3, row
