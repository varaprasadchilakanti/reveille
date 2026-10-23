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
import time
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


@pytest.mark.skipif(not hasattr(os, "waitid"), reason="POSIX waitid")
def test_a_stop_ends_every_running_command_and_leaves_the_wait_to_its_owner() -> None:
    """A streamed command and a waited one, as two worker threads would hold them."""
    from reveille.adapters.git_reader import _Silence, resume_git, stop_running_git

    streamed = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    waited = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    watchdog = threading.Timer(60, lambda _pid: None, args=(waited.pid,))
    watchdog.start()
    try:
        _Silence(streamed)

        stop_running_git()

        # Not reaped by the stop: each owner still reads the kill as its exit status.
        assert streamed.wait(timeout=10) == -9
        assert waited.wait(timeout=10) == -9
    finally:
        resume_git()
        watchdog.cancel()
        for command in (streamed, waited):
            command.kill()
            command.wait()


@pytest.mark.skipif(not hasattr(os, "waitid"), reason="POSIX waitid")
def test_a_stop_signals_no_process_already_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    from reveille.adapters.git_reader import resume_git, stop_running_git

    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    watchdog = threading.Timer(60, lambda _pid: None, args=(done.pid,))
    watchdog.start()
    sent: list[int] = []
    monkeypatch.setattr(os, "kill", lambda pid, _sig: sent.append(pid))
    try:
        stop_running_git()
    finally:
        resume_git()
        watchdog.cancel()

    assert done.pid not in sent


@pytest.mark.skipif(not hasattr(os, "waitid"), reason="POSIX waitid")
def test_a_stop_leaves_a_command_that_has_exited_for_its_owner_to_wait_on() -> None:
    """Asking whether it still runs must not reap it, or its owner reads no exit status."""
    from reveille.adapters.git_reader import resume_git, stop_running_git

    exited = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    while os.waitid(os.P_PID, exited.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        time.sleep(0.01)
    watchdog = threading.Timer(60, lambda _pid: None, args=(exited.pid,))
    watchdog.start()
    try:
        stop_running_git()
    finally:
        resume_git()
        watchdog.cancel()

    assert exited.wait(timeout=10) == 3


@pytest.mark.skipif(not hasattr(os, "waitid"), reason="POSIX waitid")
def test_a_command_started_after_a_stop_is_stopped_as_it_starts() -> None:
    """A worker between two commands would otherwise run the next to its end."""
    from reveille.adapters.git_reader import _Silence, resume_git, stop_running_git
    from reveille.exceptions import RepositoryError

    stop_running_git()
    later = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _Silence(later)
        assert later.wait(timeout=10) == -9
        with pytest.raises(RepositoryError, match="stopping"):
            _TimedGit().execute(["git", "version"])
    finally:
        resume_git()
        later.kill()
        later.wait()
    assert "git version" in _TimedGit().execute(["git", "version"]), "positive control: resumed"
