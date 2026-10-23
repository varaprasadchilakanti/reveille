# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

""" "Check the path" is said only of a path no commit ever changed.

A sparse checkout leaves tracked files off the disk, and a deleted file is
gone from it; both were told to check the path, as a typo is.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError
from typer.testing import CliRunner

from reveille.adapters.git_reader import GitReader
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_TYPO = "nothing by that name is in the working tree: check the path"
_OUTSIDE = "commits outside the window or the filters did"


def _commit(repo: Path, message: str, day: str, *args: str) -> None:
    when = {"GIT_AUTHOR_DATE": f"{day}T12:00:00Z", "GIT_COMMITTER_DATE": f"{day}T12:00:00Z"}
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", message, *args],
        cwd=repo,
        check=True,
        env={**os.environ, **when},
    )


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("typo") / "r"
    (path / "docs").mkdir(parents=True)
    (path / "src").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for name in ("docs/d.txt", "src/s.txt", "gone.txt"):
        (path / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    _commit(path, "a", "2025-01-01")
    subprocess.run(["git", "rm", "-q", "gone.txt"], cwd=path, check=True)
    _commit(path, "rm", "2025-02-01")
    subprocess.run(["git", "sparse-checkout", "set", "src"], cwd=path, check=True)
    assert not (path / "docs").exists(), "left out by the sparse checkout"
    return path


def _who(repo: Path, path: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        app, ["who-changed", path, "--repo", str(repo), "--since", "2026-01-01"]
    )
    return result.exit_code, " ".join(result.stderr.split())


@pytest.mark.parametrize("path", ["docs/d.txt", "gone.txt"], ids=["sparse", "deleted"])
def test_a_path_the_history_has_is_not_called_a_typo(repo: Path, path: str) -> None:
    code, stderr = _who(repo, path)

    assert code == ExitCode.NEGATIVE, stderr
    assert _TYPO not in stderr
    assert f"No commit in the analysis window changed '{path}'; {_OUTSIDE}." in stderr


def test_a_path_no_commit_ever_had_is_called_a_typo(repo: Path) -> None:
    code, stderr = _who(repo, "typo.txt")

    assert code == ExitCode.NEGATIVE, stderr
    assert _TYPO in stderr


def test_a_path_on_disk_gets_neither(repo: Path) -> None:
    code, stderr = _who(repo, "src/s.txt")

    assert code == ExitCode.NEGATIVE, stderr
    assert _TYPO not in stderr and _OUTSIDE not in stderr


def test_when_git_cannot_say_neither_is_claimed(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = GitReader.ever_changed

    def failing(self: GitReader, path: str, rev: str) -> Any:
        runner = self._git

        class _Failing:
            def __getattr__(self, name: str) -> Any:
                if name == "rev_list":
                    raise GitCommandError("rev-list", 128)
                return getattr(runner(), name)

        monkeypatch.setattr(self, "_git", lambda extra=(): _Failing())
        return real(self, path, rev)

    monkeypatch.setattr(GitReader, "ever_changed", failing)

    code, stderr = _who(repo, "typo.txt")

    assert code == ExitCode.NEGATIVE, stderr
    assert _TYPO not in stderr and _OUTSIDE not in stderr
