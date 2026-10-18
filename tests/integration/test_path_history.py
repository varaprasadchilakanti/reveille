# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A pathspec must not change which commits exist, only which of them count.

Git simplifies history when given a path: a branch merged without keeping its
changes (`git merge -s ours`) is skipped, though every unscoped figure counts it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _commit(repo: Path, name: str, email: str, message: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "C",
        "GIT_COMMITTER_EMAIL": "c@e.test",
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main` holds `src/a`; branch `side` changed `src/a` and was merged `-s ours`."""
    path = tmp_path / "r"
    (path / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "src" / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "base")
    subprocess.run(["git", "switch", "-qc", "side"], cwd=path, check=True)
    (path / "src" / "a").write_text("side\n", encoding="utf-8")
    _commit(path, "Sid", "sid@e.test", "side change")
    subprocess.run(["git", "switch", "-q", "main"], cwd=path, check=True)
    (path / "src" / "a").write_text("2\n", encoding="utf-8")
    _commit(path, "Ana", "ana@e.test", "main change")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=C",
            "-c",
            "user.email=c@e.test",
            "merge",
            "-q",
            "-s",
            "ours",
            "side",
            "-m",
            "merge",
        ],
        cwd=path,
        check=True,
    )
    return path


def test_who_changed_counts_a_commit_on_a_branch_merged_without_its_change(repo: Path) -> None:
    result = CliRunner().invoke(
        app, ["who-changed", "src/a", "--repo", str(repo), "--format", "json"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "sid@e.test" in result.stdout
    assert json.loads(result.stdout)["commits"] == 3
