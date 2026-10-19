# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A tag named like the checked-out branch does not stand in for it.

Git reads `refs/tags/<name>` before `refs/heads/<name>`, so a tag `main` on an
old commit made every figure describe that commit, while the report still
named the branch.
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
    _git(tmp_path, "init", "-q", "-b", "main")
    for n in range(3):
        (tmp_path / "f.txt").write_text(str(n), encoding="utf-8")
        _git(tmp_path, "add", "f.txt")
        _git(tmp_path, "commit", "-qm", f"c{n}")
    _git(tmp_path, "tag", "main", "HEAD~2")
    assert _git(tmp_path, "rev-list", "--count", "main") == "1", "positive control"
    return tmp_path


def _json(*args: str) -> dict:
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return dict(json.loads(result.stdout))


def test_the_counts_are_the_branch(repo: Path) -> None:
    assert _json("summary", "--repo", str(repo))["totals"]["commits"] == 3
    assert _json("who-changed", "f.txt", "--repo", str(repo))["commits"] == 3
    assert _json("brief", "--since", "2000-01-01", "--repo", str(repo))["totals"]["commits"] == 3


def test_the_report_names_the_branch_and_pins_its_tip(repo: Path) -> None:
    report = _json("generate", "-q", "-o", "-", "--repo", str(repo))

    assert report["metadata"]["total_commits"] == 3
    assert report["metadata"]["analysed_branch"] == "main"
    assert report["provenance"]["head_sha"] == _git(repo, "rev-parse", "HEAD")
