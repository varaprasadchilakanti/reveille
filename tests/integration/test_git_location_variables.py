# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`--repo` decides what is read, whatever Git location variables the caller has set.

A hook runs with GIT_DIR and often GIT_WORK_TREE or GIT_INDEX_FILE set. Git
honours them over the repository's own layout, so `state` listed another
directory's files as untracked, and `who-changed` gave the negative answer for
a directory with history.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    (path / "d1").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "d1" / "f").write_text("f", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    path = tmp_path / "elsewhere"
    (path / "stray").mkdir(parents=True)
    (path / "stray" / "x").write_text("x", encoding="utf-8")
    return path


def _json(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    return result.exit_code, json.loads(result.stdout) if result.stdout else {}


def test_a_work_tree_elsewhere_changes_no_answer(
    repo: Path, elsewhere: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))

    code, state = _json("state", "--repo", str(repo))
    assert code == ExitCode.SUCCESS
    assert state["clean"] is True, state

    code, answer = _json("who-changed", "d1", "--repo", str(repo))
    assert code == ExitCode.SUCCESS and answer["commits"] == 1


@pytest.mark.parametrize("variable", ["GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"])
def test_an_index_or_object_store_elsewhere_changes_no_answer(
    repo: Path, elsewhere: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    # An existing directory, as a pre-receive hook's quarantine is; one that does not
    # exist makes GitPython refuse the repository (exit 2), before any Git runs.
    monkeypatch.setenv(variable, str(elsewhere / "stray"))

    code, state = _json("state", "--repo", str(repo))
    assert code == ExitCode.SUCCESS and state["clean"] is True, state
    code, summary = _json("summary", "--repo", str(repo))
    assert code == ExitCode.SUCCESS and summary["totals"]["commits"] == 1


def test_core_worktree_elsewhere_is_refused_with_one_set(
    repo: Path, elsewhere: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git's answer follows the caller's variable, so the setting itself is read."""
    subprocess.run(["git", "config", "core.worktree", str(elsewhere)], cwd=repo, check=True)
    monkeypatch.setenv("GIT_WORK_TREE", str(repo))

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "sets its working tree" in result.stderr, result.stderr
