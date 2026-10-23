# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A signal sent to Reveille alone stops the Git command it is waiting for.

Ctrl-C in a terminal reaches the whole process group, Git included. `kill <pid>`
reaches Reveille only: it exited, and a `git status` blocked opening a named
pipe as `.gitignore` ran on with no deadline, since the deadline died with it.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not Path("/proc/self/task").is_dir() or not hasattr(os, "mkfifo"),
        reason="reads a process's children from /proc; needs a named pipe",
    ),
]

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


def _git_status_children(pid: int) -> list[int]:
    """The `git status` processes `pid` started: the command that blocks on the pipe."""
    found: list[int] = []
    for task in Path(f"/proc/{pid}/task").iterdir():
        with contextlib.suppress(OSError):
            found += [int(c) for c in (task / "children").read_text().split()]
    status: list[int] = []
    for child in found:
        with contextlib.suppress(OSError):
            if b"status" in Path(f"/proc/{child}/cmdline").read_bytes().split(b"\0"):
                status.append(child)
    return status


def _alive(pid: int) -> bool:
    """Running, not a zombie waiting to be reaped."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.fixture
def blocked(tmp_path: Path) -> Path:
    """A repository whose `.gitignore` is a named pipe nobody writes."""
    path = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    identity = ["-c", "user.name=A", "-c", "user.email=a@e.test"]
    subprocess.run(
        ["git", *identity, "commit", "-q", "--allow-empty", "-m", "a"], cwd=path, check=True
    )
    os.mkfifo(path / ".gitignore")
    return path


@pytest.mark.parametrize(("name", "code"), [("SIGTERM", 143), ("SIGHUP", 129), ("SIGINT", 130)])
def test_the_git_child_is_gone_when_reveille_exits(blocked: Path, name: str, code: int) -> None:
    reveille = subprocess.Popen(
        [sys.executable, "-c", _CHILD, "state", "--repo", str(blocked)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    git: list[int] = []
    try:
        deadline = time.monotonic() + 30
        while not git and time.monotonic() < deadline and reveille.poll() is None:
            time.sleep(0.05)
            git = _git_status_children(reveille.pid)
        assert git, "positive control: `git status` was started and is blocked"
        time.sleep(0.2)  # into the wait, past the start of the call
        reveille.send_signal(getattr(signal, name))
        reveille.wait(timeout=30)

        assert reveille.returncode == code, reveille.stderr.read() if reveille.stderr else ""
        deadline = time.monotonic() + 5
        while any(_alive(pid) for pid in git) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not any(_alive(pid) for pid in git), f"Git {git} still runs"
    finally:
        reveille.kill()
        reveille.wait()
        for pid in git:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
