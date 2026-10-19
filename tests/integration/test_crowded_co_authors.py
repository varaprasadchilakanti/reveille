# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Commits naming more co-authors than are credited are reported once, not once each.

A warning per commit put one line on stderr for every commit in the window,
which buried every other note.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_COMMITS = 5
_CO_AUTHORS = 34  # two more than are credited


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args], cwd=repo, check=True
    )


def test_crowded_commits_are_one_warning(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    trailers = "\n".join(f"Co-authored-by: P{i} <p{i}@e.test>" for i in range(_CO_AUTHORS))
    for n in range(_COMMITS):
        (tmp_path / f"f{n}").write_text(str(n), encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-qm", f"c{n}\n\n{trailers}")

    result = CliRunner().invoke(app, ["summary", "--repo", str(tmp_path)])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    warnings = [line for line in result.stderr.splitlines() if "co-authors" in line]
    [warning] = warnings
    assert warning.endswith(
        f"{_COMMITS} commits name more than 32 co-authors; {2 * _COMMITS} ignored"
    ), result.stderr
