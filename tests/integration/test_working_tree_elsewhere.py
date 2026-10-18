# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A repository cannot point Reveille at another directory with `core.worktree`.

`.git/config` travels in an archive or a copied directory. Before, Reveille run in
such a repository read the other repository's history and wrote the report into
it, under the name of neither. A linked worktree and a submodule keep working.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _repo(path: Path, email: str) -> Path:
    path.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "N",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "N",
        "GIT_COMMITTER_EMAIL": email,
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "f.txt").write_text(email, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=path, check=True, env=env)
    return path


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    """`hostile` sets `core.worktree` to `victim`, another repository."""
    victim = _repo(tmp_path / "victim", "victim@private.test")
    hostile = _repo(tmp_path / "hostile", "h@e.test")
    subprocess.run(["git", "config", "core.worktree", str(victim)], cwd=hostile, check=True)
    (hostile / "sub").mkdir()
    return hostile, victim


@pytest.mark.parametrize("command", ["generate", "summary", "brief", "state"])
@pytest.mark.parametrize("where", ["root", "subdirectory"])
def test_it_is_refused_and_nothing_is_written_into_the_other_repository(
    pair: tuple[Path, Path], command: str, where: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile, victim = pair
    monkeypatch.chdir(hostile if where == "root" else hostile / "sub")
    before = sorted(p.name for p in victim.iterdir())
    args = [command, "--since", "2000-01-01"] if command == "brief" else [command]

    result = CliRunner().invoke(app, args)

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stdout
    assert "core.worktree" in result.stderr
    assert "victim@private.test" not in result.stdout
    assert sorted(p.name for p in victim.iterdir()) == before


def test_a_working_tree_set_to_a_plain_directory_is_refused_by_name(tmp_path: Path) -> None:
    """Before, this said the other directory 'is not a valid Git repository'."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    hostile = _repo(tmp_path / "hostile", "h@e.test")
    subprocess.run(["git", "config", "core.worktree", str(elsewhere)], cwd=hostile, check=True)

    result = CliRunner().invoke(app, ["summary", "--repo", str(hostile)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "core.worktree" in result.stderr


def test_repos_lists_it_as_not_read(pair: tuple[Path, Path]) -> None:
    hostile, _ = pair

    result = CliRunner().invoke(app, ["repos", str(hostile.parent), "--format", "csv"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert any(
        line.startswith("hostile,not read") and "core.worktree" in line
        for line in result.stdout.splitlines()
    )


def test_a_linked_worktree_and_a_submodule_are_still_read(tmp_path: Path) -> None:
    main = _repo(tmp_path / "main", "m@e.test")
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "side", str(tmp_path / "linked")],
        cwd=main,
        check=True,
    )
    _repo(tmp_path / "subsource", "s@e.test")
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(tmp_path / "subsource"),
            "sub",
        ],
        cwd=main,
        check=True,
    )

    for where in (tmp_path / "linked", main / "sub", main):
        result = CliRunner().invoke(app, ["summary", "--repo", str(where)])
        assert result.exit_code == ExitCode.SUCCESS, (where, result.stderr)
