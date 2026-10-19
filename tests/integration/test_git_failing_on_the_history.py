# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""When Git cannot read a history whose branch exists, Reveille says Git's reason.

The advice was to check the branch name, which was right, followed by the whole
of Git's stderr, hint first. A tree deeper than `core.maxTreeDepth` is one such
cause; the repository's own config sets the limit here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f").write_text("f", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "core.maxTreeDepth", "1"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize(
    "args", [["validate"], ["generate", "-q", "-o", "-"], ["who-changed", "a"]]
)
def test_gits_reason_is_given_and_the_branch_is_not_blamed(repo: Path, args: list[str]) -> None:
    result = CliRunner().invoke(app, [*args, "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "exceeded maximum allowed tree depth" in result.stderr, result.stderr
    assert "Verify the branch" not in result.stderr and "hint:" not in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1, result.stderr
