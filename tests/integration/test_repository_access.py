# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Repositories Git reads differently are answered, or refused; never "no commits".

Both cases below used to report "contains no commits" with exit 1, a confident
negative answer about a repository that has commits.
"""

from __future__ import annotations

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


def _repo(path: Path, *init: str) -> Path:
    path.mkdir()
    env = {**os.environ, **_WHO}
    subprocess.run(["git", "init", "-q", "-b", "main", *init], cwd=path, check=True)
    for name in ("a.txt", "b.txt"):
        (path / name).write_text(name, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-qm", name],
            cwd=path,
            check=True,
            env=env,
        )
    return path


def test_a_repository_owned_by_someone_else_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "r")
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "safe.directory" in result.stderr
    assert "no commits" not in result.stderr


def test_a_sha256_repository_cannot_run_yet(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r", "--object-format=sha256")

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "SHA-256" in result.stderr
    assert "no commits" not in result.stderr
