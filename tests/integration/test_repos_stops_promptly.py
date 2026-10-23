# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`repos` stopped by a signal stops the Git its worker threads wait on, and exits at once.

The signal reaches the main thread only. The pool waited for its workers on the
way out, so each read under way ran to its end first: seconds on large
repositories, and a Git command that never ended kept Reveille running.
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
    pytest.mark.skipif(not hasattr(os, "waitid"), reason="POSIX signals and waitid"),
]

# Each row's read waits on a minute-long command, started as Reveille starts a streamed Git.
_CHILD = """
import subprocess, sys, time
from reveille.adapters import git_reader
import reveille.services.report as report
def slow_row(path, *args):
    command = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    git_reader._Silence(command)
    print(command.pid, file=sys.stderr, flush=True)
    command.wait()
    raise git_reader.RepositoryError("stopped")
report._repository_row = slow_row
from reveille.cli import app
sys.argv = ["reveille", *sys.argv[1:]]
app()
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    for name in ("a", "b"):
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path / name)], check=True)
    return tmp_path


@pytest.mark.parametrize(("name", "code"), [("SIGTERM", 143), ("SIGHUP", 129)])
def test_the_run_ends_without_waiting_for_the_reads(workspace: Path, name: str, code: int) -> None:
    reveille = subprocess.Popen(
        [sys.executable, "-c", _CHILD, "repos", str(workspace)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert reveille.stderr is not None
    slow = [int(reveille.stderr.readline()) for _ in range(2)]  # both reads are waiting
    try:
        sent = time.monotonic()
        reveille.send_signal(getattr(signal, name))
        reveille.wait(timeout=30)

        assert reveille.returncode == code
        assert time.monotonic() - sent < 10, "the run waited for the reads under way"
        for pid in slow:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)  # stopped, and waited for by its owner
    finally:
        reveille.kill()
        reveille.wait()
        for pid in slow:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
