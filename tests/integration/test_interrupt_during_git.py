# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Ctrl-C while Reveille waits on Git stops it at once, not at the Git deadline."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


def _git_whose_status_waits(tmp_path: Path, started: Path) -> Path:
    real = shutil.which("git")
    assert real is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        f'  if [ "$a" = status ]; then : > "{started}"; exec sleep 600; fi\n'
        "done\n"
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    git.chmod(0o755)
    return bin_dir


@pytest.mark.skipif(sys.platform == "win32", reason="GitPython sets no deadline on Windows")
def test_an_interrupt_while_git_runs_exits_promptly(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
    )
    started = tmp_path / "status-started"
    bin_dir = _git_whose_status_waits(tmp_path, started)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, "state", "--repo", str(repo)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not started.exists():
            assert child.poll() is None, child.stderr.read() if child.stderr else ""
            assert time.monotonic() < deadline, "git status was never run"
            time.sleep(0.05)

        child.send_signal(signal.SIGINT)
        interrupted = time.monotonic()
        child.wait(timeout=60)

        assert time.monotonic() - interrupted < 10, "waited for the 120 s deadline timer"
        assert child.returncode == 130
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()
