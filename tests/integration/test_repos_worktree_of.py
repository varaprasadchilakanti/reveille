# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`repos` names the main working tree of a linked worktree, which is a row of its own."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.adapters.git_reader import main_worktree_of
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_ENV = {
    "GIT_AUTHOR_NAME": "A",
    "GIT_AUTHOR_EMAIL": "a@e.test",
    "GIT_COMMITTER_NAME": "A",
    "GIT_COMMITTER_EMAIL": "a@e.test",
    "GIT_AUTHOR_DATE": "2026-10-10T10:00:00Z",
    "GIT_COMMITTER_DATE": "2026-10-10T10:00:00Z",
}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, **_ENV},
    )


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "f").write_text("f\n", encoding="utf-8")
    _git(path, "add", "f")
    _git(path, "commit", "-qm", "f")
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "team"
    main = _repo(root / "api")
    _git(main, "worktree", "add", "-q", str(root / "api-fix"), "-b", "fix")
    away = _repo(tmp_path / "away")
    _git(away, "worktree", "add", "-q", str(root / "away-wt"), "-b", "wt")
    _git(tmp_path, "clone", "-q", "--bare", str(main), str(root / "store.git"))
    _git(root / "store.git", "worktree", "add", "-q", str(root / "store-wt"), "main")
    holder = _repo(root / "holder")
    _git(holder, "submodule", "add", "-q", str(main), "sub")
    return root


def _rows(root: Path) -> dict[str, dict[str, object]]:
    result = CliRunner().invoke(
        app, ["repos", str(root), "--format", "json", "--until", "2026-10-17", "--depth", "1"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return {row["path"]: row for row in json.loads(result.stdout)["repositories"]}


def test_a_linked_worktree_names_its_main_tree(workspace: Path) -> None:
    rows = _rows(workspace)

    assert rows["api-fix"]["worktree_of"] == "api"
    assert rows["store-wt"]["worktree_of"] == "store.git"


def test_a_main_tree_outside_the_directory_is_not_named(workspace: Path) -> None:
    rows = _rows(workspace)

    assert rows["away-wt"]["worktree_of"] == "(a path outside the directory)"
    assert str(workspace.parent) not in json.dumps(rows)


def test_a_repository_that_is_not_a_linked_worktree_names_none(workspace: Path) -> None:
    rows = _rows(workspace)

    for path in ("api", "store.git", "holder"):
        assert rows[path]["worktree_of"] is None, path
    # A submodule's `.git` is a file too, and its Git directory has no `commondir`.
    assert main_worktree_of(workspace / "holder" / "sub") is None
    assert main_worktree_of(workspace / "api-fix") == (workspace / "api").resolve()


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("text", "- api-fix: active, last commit 2026-10-10 (7 days ago); 1 commit by 1 person"),
        ("markdown", "| `api-fix` (worktree of `api`) | active |"),
    ],
)
def test_the_main_tree_is_in_every_format(
    workspace: Path, output_format: str, expected: str
) -> None:
    result = CliRunner().invoke(
        app, ["repos", str(workspace), "--format", output_format, "--until", "2026-10-17"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert expected in result.stdout
    if output_format == "text":
        [line] = [x for x in result.stdout.splitlines() if x.startswith("- api-fix:")]
        assert line.endswith("in the window; worktree of api")


def test_csv_carries_the_column_last(workspace: Path) -> None:
    result = CliRunner().invoke(
        app, ["repos", str(workspace), "--format", "csv", "--until", "2026-10-17"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    reader = csv.DictReader(io.StringIO(result.stdout.lstrip("﻿")))
    assert reader.fieldnames is not None and reader.fieldnames[-1] == "worktree_of"
    rows = {row["path"]: row["worktree_of"] for row in reader}
    assert rows["api-fix"] == "api"
    assert rows["api"] == ""


def test_an_empty_or_unreadable_commondir_names_no_main_tree(workspace: Path) -> None:
    linked = workspace / "api-fix"
    commondir = workspace / "api" / ".git" / "worktrees" / "api-fix" / "commondir"

    commondir.write_bytes(b"\n")
    assert main_worktree_of(linked) is None
    commondir.write_bytes(b"\xff\n")
    assert main_worktree_of(linked) is None
