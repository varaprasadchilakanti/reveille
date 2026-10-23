# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""An interrupted Git call cancels the deadline timer it started, and nothing else.

`tests/integration/test_interrupt_during_git.py` runs Reveille as a child process and
times the exit; this checks the same clean-up in-process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any

import pytest

from reveille.adapters.git_reader import _stop_child, _TimedGit

pytestmark = pytest.mark.unit


def test_only_the_timers_the_call_started_are_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    earlier = threading.Timer(60, lambda: None)
    earlier.start()
    started: dict[str, Any] = {}

    def interrupted(*_args: Any, **_kwargs: Any) -> None:
        # GitPython's watchdog, and a thread that is not a timer.
        started["timer"] = threading.Timer(60, lambda: None)
        started["timer"].start()
        started["worker"] = threading.Thread(target=threading.Event().wait, args=(0.2,))
        started["worker"].start()
        raise KeyboardInterrupt

    monkeypatch.setattr(_TimedGit, "_execute_timed", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            _TimedGit().execute(["git", "version"])

        # `cancel()` sets `finished` at once; the thread exits a moment later.
        assert started["timer"].finished.is_set(), "the call's timer still waits"
        assert not earlier.finished.is_set(), "a timer started before the call was cancelled"
    finally:
        earlier.cancel()
        started["timer"].cancel()
        started["worker"].join(timeout=5)


@pytest.mark.skipif(not hasattr(os, "WNOHANG"), reason="POSIX process waiting")
def test_an_interrupted_call_stops_the_command_its_watchdog_was_set_for() -> None:
    command = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _stop_child(threading.Timer(60, lambda _pid: None, args=(command.pid,)))

        with pytest.raises(ChildProcessError):
            os.waitpid(command.pid, os.WNOHANG)  # stopped and waited for
    finally:
        command.kill()
        command.wait()


@pytest.mark.skipif(not hasattr(os, "WNOHANG"), reason="POSIX process waiting")
def test_a_command_already_waited_for_is_not_signalled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its process ID may belong to another process by now."""
    command = subprocess.Popen([sys.executable, "-c", "pass"])
    command.wait()
    sent: list[int] = []
    monkeypatch.setattr(os, "kill", lambda pid, _sig: sent.append(pid))

    _stop_child(threading.Timer(60, lambda _pid: None, args=(command.pid,)))
    _stop_child(threading.Timer(60, lambda: None))  # a timer that holds no process ID

    assert sent == []
