# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`brief --until` alone starts at the latest tag on or before that day (ADR 0031).

It started at the latest tag on the branch, which can be after `--until`: a brief
from March to January, empty or wrong.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.adapters.git_reader import GitReader
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _commit(repo: Path, name: str, day: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    when = {"GIT_AUTHOR_DATE": f"{day}T12:00:00Z", "GIT_COMMITTER_DATE": f"{day}T12:00:00Z"}
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", name],
        cwd=repo,
        check=True,
        env={**os.environ, **when},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """v1 on 5 January, v2 on 5 March, one commit after each."""
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for name, day, tag in [
        ("a", "2026-01-05", "v1"),
        ("b", "2026-01-20", None),
        ("c", "2026-03-05", "v2"),
        ("d", "2026-03-20", None),
    ]:
        _commit(path, name, day)
        if tag:
            subprocess.run(["git", "tag", tag], cwd=path, check=True)
    return path


def _brief(repo: Path, *args: str) -> tuple[int, dict | None, str]:
    result = CliRunner().invoke(app, ["brief", "--repo", str(repo), "--format", "json", *args])
    document = json.loads(result.stdout) if result.exit_code == 0 else None
    return result.exit_code, document, result.stderr


def test_with_until_it_starts_at_the_tag_before_it(repo: Path) -> None:
    code, document, stderr = _brief(repo, "--until", "2026-02-01")

    assert code == ExitCode.SUCCESS, stderr
    assert document is not None
    assert document["point"]["from"] == "v1"
    assert document["totals"]["commits"] == 1  # b only


def test_a_tag_on_the_until_day_is_the_start(repo: Path) -> None:
    code, _, stderr = _brief(repo, "--until", "2026-03-05")

    assert code == ExitCode.NEGATIVE, stderr
    assert "No commits since v2 up to 2026-03-05 (--until)." in stderr


def test_without_until_it_starts_at_the_latest_tag(repo: Path) -> None:
    """Positive control: ADR 0025's behaviour is unchanged."""
    code, document, _ = _brief(repo)

    assert code == ExitCode.SUCCESS
    assert document is not None and document["point"]["from"] == "v2"


def test_no_tag_on_or_before_until_cannot_run_and_says_so(repo: Path) -> None:
    code, _, stderr = _brief(repo, "--until", "2025-12-31")

    assert code == ExitCode.CANNOT_RUN
    assert "no tag on or before 2025-12-31" in stderr


def test_the_lookup_writes_nothing_and_starts_no_program(repo: Path, tmp_path: Path) -> None:
    """Measured as every Git call is: the repository's own config names a program."""
    marker = tmp_path / "ran"
    program = tmp_path / "prog"
    program.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    program.chmod(0o755)
    for key, value in [
        ("core.fsmonitor", str(program)),
        ("gpg.program", str(program)),
        ("log.showSignature", "true"),
        ("core.hooksPath", str(tmp_path)),
    ]:
        subprocess.run(["git", "config", key, value], cwd=repo, check=True)
    git_dir = repo / ".git"
    before = sorted((p, p.stat().st_mtime_ns) for p in git_dir.rglob("*") if p.is_file())

    tag = GitReader(repo).latest_tag("refs/heads/main", datetime.date(2026, 2, 1))

    assert tag == "v1"
    assert sorted((p, p.stat().st_mtime_ns) for p in git_dir.rglob("*") if p.is_file()) == before
    assert not marker.exists()
    subprocess.run(["git", "status"], cwd=repo, capture_output=True, check=True)
    assert marker.exists(), "positive control: plain git status runs core.fsmonitor"
