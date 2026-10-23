# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A named pipe where Git reads ignore or attribute rules stops Reveille, not hangs it.

Git opens `.gitignore` (for `git status`) and `.gitattributes` (to count lines)
itself, and blocks reading a FIFO until something writes to it: for ever. A
copied directory or an archive can carry one; `git clone` cannot. `state` now
stops `git status` after a time limit, and a line-count read checks the
attribute files first.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX"),
]

# The child shortens the status limit so a stopped `git status` takes seconds.
_CHILD = (
    "import sys, reveille.adapters.git_reader as g; g.STATUS_TIMEOUT_SECONDS = 2; "
    "from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    (path / "d").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "d" / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run the CLI in a child process; None if it had to be killed."""
    try:
        return subprocess.run(
            [sys.executable, "-c", _CHILD, *args, "--repo", str(repo)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None


@pytest.mark.parametrize("where", [".gitignore", "d/.gitignore", ".git/info/exclude"])
def test_state_stops_rather_than_waiting_for_ever(repo: Path, where: str) -> None:
    target = repo / where
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    os.mkfifo(target)

    done = _run(repo, "state")

    assert done is not None, "state hung"
    assert done.returncode == 2
    assert "did not finish within 2 seconds" in done.stderr


@pytest.mark.parametrize("where", [".gitattributes", "d/.gitattributes", ".git/info/attributes"])
def test_generate_refuses_an_attribute_file_that_blocks(
    repo: Path, tmp_path: Path, where: str
) -> None:
    target = repo / where
    target.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(target)

    done = _run(repo, "generate", "--format", "json", "-o", str(tmp_path / "out.json"))

    assert done is not None, "generate hung"
    assert done.returncode == 2
    assert "is not a regular file" in done.stderr
    assert where.split("/")[-1] in done.stderr


def test_a_linked_worktree_checks_the_attributes_its_main_repository_holds(
    repo: Path, tmp_path: Path
) -> None:
    """A linked worktree has a Git directory of its own; `info/` is in the common one."""
    worktree = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(worktree)], cwd=repo, check=True)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    os.mkfifo(repo / ".git" / "info" / "attributes")

    done = _run(worktree, "generate", "--format", "json", "-o", str(tmp_path / "out.json"))

    assert done is not None, "generate hung"
    assert done.returncode == 2
    assert "attributes" in done.stderr


def test_a_configured_attributes_file_that_blocks_is_refused(repo: Path, tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "attributes")
    subprocess.run(
        ["git", "config", "core.attributesFile", str(tmp_path / "attributes")], cwd=repo, check=True
    )

    done = _run(repo, "generate", "--format", "json", "-o", str(tmp_path / "out.json"))

    assert done is not None, "generate hung"
    assert done.returncode == 2


@pytest.mark.parametrize("command", [("summary",), ("brief", "--since", "2000-01-01")])
def test_a_read_without_line_counts_is_not_refused(repo: Path, command: tuple[str, ...]) -> None:
    """They do not read attributes, so the check does not stand in their way."""
    os.mkfifo(repo / ".gitattributes")

    done = _run(repo, *command)

    assert done is not None, f"{command[0]} hung"
    assert done.returncode == 0, done.stderr


def test_regular_rule_files_are_read_as_before(repo: Path, tmp_path: Path) -> None:
    (repo / ".gitattributes").write_text("*.bin binary\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")

    for args in (("state",), ("generate", "--format", "json", "-o", str(tmp_path / "o.json"))):
        done = _run(repo, *args)
        assert done is not None and done.returncode == 0, (args, done and done.stderr)


def test_a_directory_only_older_history_had_is_checked(repo: Path, tmp_path: Path) -> None:
    """Not in HEAD, but on disk: Git looks up the old path's attributes there."""
    (repo / "old").mkdir()
    (repo / "old" / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "b"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "rm", "-rq", "old"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "c"],
        cwd=repo,
        check=True,
    )
    (repo / "old").mkdir()
    os.mkfifo(repo / "old" / ".gitattributes")

    done = _run(repo, "generate", "--format", "json", "-o", str(tmp_path / "out.json"))

    assert done is not None, "generate hung"
    assert done.returncode == 2
    assert "old" in done.stderr


@pytest.mark.parametrize(
    "command", [["generate", "-q", "-o", "r.html"], ["brief", "--since", "2000-01-01"]]
)
def test_an_order_file_that_blocks_is_not_read(repo: Path, command: list[str]) -> None:
    """`diff.orderFile` is read by every diff Git prints, line counts included."""
    os.mkfifo(repo / ".git" / "order")
    subprocess.run(["git", "config", "diff.orderFile", ".git/order"], cwd=repo, check=True)
    try:
        subprocess.run(
            ["git", "log", "--numstat"], cwd=repo, capture_output=True, timeout=5, check=False
        )
        blocked = False
    except subprocess.TimeoutExpired:
        blocked = True
    assert blocked, "positive control: plain Git waits on the pipe"

    done = _run(repo, *[str(repo / c) if c == "r.html" else c for c in command])

    assert done is not None, "Reveille waited on the pipe"
    assert done.returncode == 0, done.stderr
