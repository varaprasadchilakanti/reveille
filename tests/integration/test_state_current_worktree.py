# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`state` marks the worktree it read, and lists the others as the others.

Read in a linked worktree, the text listed every worktree after the main one as
"other", itself included, and left the main tree out.
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


def _git(cwd: Path, *args: str) -> None:
    identity = {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.test"}
    identity |= {"GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.test"}
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **identity}
    )


@pytest.fixture
def trees(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "commit", "-q", "--allow-empty", "-m", "c")
    _git(main, "worktree", "add", "-q", str(tmp_path / "side"), "-b", "side")
    _git(main, "worktree", "add", "-q", str(tmp_path / "third"), "-b", "third")
    return tmp_path


def _state(repo: Path, output_format: str) -> str:
    result = CliRunner().invoke(app, ["state", "--repo", str(repo), "--format", output_format])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


@pytest.mark.parametrize("read", ["main", "side"])
def test_json_marks_the_worktree_read(trees: Path, read: str) -> None:
    worktrees = json.loads(_state(trees / read, "json"))["worktrees"]

    current = {Path(w["path"]).name: w["current"] for w in worktrees}
    assert current == {"main": read == "main", "side": read == "side", "third": False}


def test_text_from_a_linked_worktree_lists_the_main_tree_not_itself(trees: Path) -> None:
    text = _state(trees / "side", "text")

    assert f"2 other worktrees: {trees / 'main'} (main), {trees / 'third'} (third)." in text
    assert f"{trees / 'side'} (side)" not in text


def test_markdown_from_a_linked_worktree_lists_the_main_tree_not_itself(trees: Path) -> None:
    markdown = _state(trees / "side", "markdown")

    [line] = [x for x in markdown.splitlines() if "Other worktrees" in x]
    assert line == f"- **Other worktrees:** `{trees / 'main'} (main)`, `{trees / 'third'} (third)`"


def test_a_bare_repository_is_its_own_current_entry(trees: Path) -> None:
    store = trees / "store.git"
    _git(trees, "clone", "-q", "--bare", str(trees / "main"), str(store))
    _git(store, "worktree", "add", "-q", str(trees / "checkout"), "main")

    worktrees = json.loads(_state(store, "json"))["worktrees"]

    assert [(Path(w["path"]).name, w["current"]) for w in worktrees] == [
        ("store.git", True),
        ("checkout", False),
    ]
