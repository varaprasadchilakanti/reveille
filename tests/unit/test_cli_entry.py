# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The CLI's entry point and its stdout writer keep the exit-code contract.

Exit 1 is the negative answer, so nothing that fails to run may end with it:
not an unexpected error, not an import that fails, and not an answer that could
not be written. These run in the test's own process, so the lines are measured;
`test_stdout_that_fails.py` and `test_git_that_cannot_start.py` run the same
cases as real programs.
"""

from __future__ import annotations

import errno
import io
import sys
from typing import Any

import pytest
import typer

from reveille import cli
from reveille.cli import ExitCode, _say, _why_git_cannot_start, app

pytestmark = pytest.mark.unit


def _run(monkeypatch: pytest.MonkeyPatch, raised: BaseException) -> int:
    """Run the app with Typer's own call replaced by one that raises `raised`."""

    def fail(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise raised

    monkeypatch.setattr(typer.Typer, "__call__", fail)
    with pytest.raises(SystemExit) as stopped:
        app()
    return int(stopped.value.code or 0)


class TestTheEntryPoint:
    def test_git_that_cannot_start_names_gits_reason(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        message = "Failed to initialize: Cmd('git') failed\n  stderr: 'fatal: bad config line 1'"

        code = _run(monkeypatch, ImportError(message))

        assert code == ExitCode.CANNOT_RUN
        assert "Git could not be started: fatal: bad config line 1" in capsys.readouterr().err

    def test_any_other_import_error_is_a_defect_and_never_exit_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run(monkeypatch, ImportError("No module named 'nothing'"))

        assert code == ExitCode.CANNOT_RUN
        assert "defect" in capsys.readouterr().err

    def test_an_unexpected_error_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(monkeypatch, RuntimeError("boom")) == ExitCode.CANNOT_RUN
        assert "RuntimeError: boom" in capsys.readouterr().err

    def test_a_deleted_current_directory_is_said_plainly(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def gone() -> str:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")

        monkeypatch.setattr(cli.os, "getcwd", gone)

        with pytest.raises(SystemExit) as stopped:
            app()

        assert stopped.value.code == ExitCode.CANNOT_RUN
        assert "current directory no longer exists" in capsys.readouterr().err


class TestWhyGitCannotStart:
    @pytest.mark.parametrize(
        ("message", "reason"),
        [
            ("Failed to initialize: Bad git executable.", "no working `git` program"),
            ("Failed to initialize: x\n  stderr: 'hint: a\nfatal: b'", "fatal: b"),
            ("Failed to initialize: x\n  stderr: 'hint: only a hint'", "no working `git`"),
        ],
    )
    def test_the_reason(self, message: str, reason: str) -> None:
        assert _why_git_cannot_start(message).startswith(reason)


class _Stdout(io.StringIO):
    def __init__(self, raised: OSError | None = None) -> None:
        super().__init__()
        self._raised = raised

    def flush(self) -> None:
        if self._raised is not None:
            raise self._raised

    def fileno(self) -> int:
        raise io.UnsupportedOperation("no descriptor")


class TestTheStdoutWriter:
    def test_an_answer_is_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _Stdout()
        monkeypatch.setattr(sys, "stdout", out)

        _say("yes")

        assert out.getvalue() == "yes\n"

    def test_a_closed_stdout_cannot_run_for_an_answer(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "stdout", None)

        with pytest.raises(typer.Exit) as stopped:
            _say("yes")

        assert stopped.value.exit_code == ExitCode.CANNOT_RUN
        assert "standard output is closed" in capsys.readouterr().err

    def test_a_closed_stdout_drops_a_confirmation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdout", None)

        _say("Report written", answer=False)  # no exit: the work was done

    def test_a_reader_that_stopped_is_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdout", _Stdout(BrokenPipeError(errno.EPIPE, "Broken pipe")))

        with pytest.raises(typer.Exit) as stopped:
            _say("yes")

        assert stopped.value.exit_code == ExitCode.SUCCESS

    def test_a_full_disk_cannot_run(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "stdout", _Stdout(OSError(errno.ENOSPC, "No space left")))

        with pytest.raises(typer.Exit) as stopped:
            _say("yes")

        assert stopped.value.exit_code == ExitCode.CANNOT_RUN
        assert "could not be written to standard output: No space left" in capsys.readouterr().err
