# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A repository with history is never reported as having none.

"No commits" is exit 1, the negative answer, which a CI gate may accept. GitPython
splits HEAD at line separators a branch name may hold, and says "no commit" for a
HEAD whose object is missing or is not a commit; Git is asked instead.
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
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    for name in ("a", "b"):
        (path / name).write_text(name, encoding="utf-8")
        _git(path, "add", name)
        _git(path, "commit", "-qm", name)
    return path


def _summary(repo: Path) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--format", "json"])
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.parametrize("separator", [0x2028, 0x2029, 0x85])
def test_a_branch_named_with_a_line_separator_is_read(repo: Path, separator: int) -> None:
    _git(repo, "branch", "-m", f"l{chr(separator)}s")

    code, out, err = _summary(repo)

    assert code == ExitCode.SUCCESS, err
    assert json.loads(out)["totals"]["commits"] == 2


@pytest.mark.parametrize("damage", ["missing", "blob"])
def test_a_head_that_names_no_commit_is_damage_not_emptiness(repo: Path, damage: str) -> None:
    target = "1" * 40 if damage == "missing" else _git(repo, "hash-object", "-w", "a")
    (repo / ".git" / "refs" / "heads" / "main").write_text(target + "\n", encoding="utf-8")

    code, _out, err = _summary(repo)

    assert code == ExitCode.CANNOT_RUN, err
    assert "damaged" in err, err


def test_an_unborn_head_is_still_the_negative_answer(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")

    code, _out, err = _summary(tmp_path)

    assert code == ExitCode.NEGATIVE, err
    assert "contains no commits" in err, err
