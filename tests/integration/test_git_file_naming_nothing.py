# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A linked worktree whose repository has gone is told so, not told to fix permissions.

Its `.git` is a readable file naming a Git directory that no longer exists; the
message once blamed the permissions on it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def test_a_git_file_naming_a_missing_directory_says_so(tmp_path: Path) -> None:
    main = tmp_path / "the main"
    main.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=main, check=True)
    (main / "a").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "a"], cwd=main, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=main,
        check=True,
    )
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "side", str(tmp_path / "a wt")], cwd=main, check=True
    )
    shutil.rmtree(main)

    result = CliRunner().invoke(app, ["summary", "--repo", str(tmp_path / "a wt")])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "permissions" not in result.stderr, result.stderr
    assert "does not exist" in result.stderr and "worktrees" in result.stderr, result.stderr
    assert f"git worktree repair '{tmp_path / 'a wt'}'" in result.stderr, result.stderr
