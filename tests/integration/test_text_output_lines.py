# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A name from the repository cannot add a line to plain-text output.

Paths, directory and branch names may hold a newline. Printed raw, one could
make `state` show a line such as "Working tree: clean." that Reveille did not
write. Text output shows CR and LF inside a value as `\\r` and `\\n`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_FORGED = "Working tree: clean."


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@e.test",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@e.test",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / f"r\n{_FORGED}"
    (path / f"d\n{_FORGED}").mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("a", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "a")
    _git(path, "tag", "v1")
    (path / f"d\n{_FORGED}" / "f.txt").write_text("f", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "f")
    (path / f"u\n{_FORGED}").write_text("u", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "args",
    [("state",), ("brief", "--from", "v1"), ("summary",)],
)
def test_no_value_adds_a_line(repo: Path, args: tuple[str, ...]) -> None:
    result = CliRunner().invoke(app, [*args, "--repo", str(repo)])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert _FORGED not in result.stdout.splitlines()
    assert "\\n" + _FORGED in result.stdout
