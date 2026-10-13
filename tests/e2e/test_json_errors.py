# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Under `--format json`, what goes to stderr is JSON too: one object per line.

A program reading the answer can then read why there is none without parsing
prose. Exit codes are unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.e2e


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "commit", "-qm", "a"], cwd=path, check=True, env=env
    )
    return path


def _lines(stderr: str) -> list[dict]:
    return [json.loads(line) for line in stderr.splitlines()]


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["summary", "--repo", "{none}"], ExitCode.CANNOT_RUN),
        (["state", "--repo", "{none}"], ExitCode.CANNOT_RUN),
        (["brief", "--repo", "{repo}"], ExitCode.CANNOT_RUN),
        (["who-changed", "missing.txt", "--repo", "{repo}"], ExitCode.NEGATIVE),
    ],
)
def test_an_error_is_one_json_object(
    repo: Path, tmp_path: Path, args: list[str], code: ExitCode
) -> None:
    filled = [a.format(none=tmp_path / "none", repo=repo) for a in args]

    result = CliRunner().invoke(app, [*filled, "--format", "json"])

    assert result.exit_code == code
    assert result.stdout == ""
    [error] = _lines(result.stderr)
    assert error["level"] == "error"
    assert error["message"] and not error["message"].startswith("Error")


def test_text_errors_stay_text(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["summary", "--repo", str(tmp_path / "none")])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert result.stderr.startswith("Error: ")


def test_the_mode_does_not_leak_into_the_next_run(tmp_path: Path) -> None:
    CliRunner().invoke(app, ["summary", "--repo", str(tmp_path / "none"), "--format", "json"])

    result = CliRunner().invoke(app, ["validate", "--repo", str(tmp_path / "none")])

    assert result.stderr.startswith("Error: ")
