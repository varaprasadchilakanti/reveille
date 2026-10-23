# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Help that cannot be written ends as an answer that cannot be does, in process.

`tests/integration/test_stdout_that_fails.py` runs these against a real
descriptor in a child; here each failure is raised where Rich or Click raises it.
"""

from __future__ import annotations

import io
import sys
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from reveille import cli
from reveille.cli import ExitCode, app


class _Context:
    """A Click context whose `get_help` returns `text` or raises `error`."""

    def __init__(self, text: str = "", error: BaseException | None = None) -> None:
        self.text, self.error = text, error

    def get_help(self) -> str:
        if self.error is not None:
            raise self.error
        return self.text


@pytest.fixture(autouse=True)
def _keep_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pointing the real descriptor at /dev/null would end pytest's own output."""
    monkeypatch.setattr(cli, "_discard_stdout", lambda: None)


def _exit_of(ctx: Any) -> int:
    with pytest.raises(typer.Exit) as stopped:
        cli._show_help(ctx)
    return stopped.value.exit_code


def test_help_returned_as_text_is_written(capsys: pytest.CaptureFixture[str]) -> None:
    """Without Rich, Click returns the help instead of printing it."""
    cli._show_help(_Context("Usage: reveille"))

    assert capsys.readouterr().out == "Usage: reveille\n"


def test_help_with_stdout_closed_cannot_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdout", None)

    assert _exit_of(_Context("Usage")) == ExitCode.CANNOT_RUN
    assert "standard output is closed" in capsys.readouterr().err


def test_help_to_a_reader_that_stopped_is_success() -> None:
    assert _exit_of(_Context(error=BrokenPipeError())) == ExitCode.SUCCESS


def test_rich_s_exit_1_for_a_broken_pipe_is_success() -> None:
    """Rich's `Console.on_broken_pipe` exits 1, which would read as a negative answer."""
    assert _exit_of(_Context(error=SystemExit(1))) == ExitCode.SUCCESS


def test_any_other_system_exit_is_passed_on() -> None:
    """Positive control: only Rich's 1 is taken for a reader that stopped."""
    with pytest.raises(SystemExit) as stopped:
        cli._show_help(_Context(error=SystemExit(3)))

    assert stopped.value.code == 3


def test_help_on_a_full_disk_cannot_run(capsys: pytest.CaptureFixture[str]) -> None:
    error = OSError(28, "No space left on device")

    assert _exit_of(_Context(error=error)) == ExitCode.CANNOT_RUN
    assert "could not be written to standard output: No space left on device" in (
        capsys.readouterr().err
    )


def test_a_confirmation_that_cannot_be_written_is_left_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A written file's path is not the answer, so a full disk is not an error for it."""

    class _Full(io.StringIO):
        def write(self, _text: str) -> int:
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(sys, "stdout", _Full())

    cli._say("Report written to: r.html", answer=False)
    assert capsys.readouterr().err == ""
    with pytest.raises(typer.Exit) as stopped:
        cli._say("the answer")
    assert stopped.value.exit_code == ExitCode.CANNOT_RUN, "positive control: an answer"


def test_no_command_gives_the_help_and_exit_2() -> None:
    result = CliRunner().invoke(app, [])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "Usage:" in result.stdout


def test_a_command_with_no_help_option_keeps_none() -> None:
    assert cli._through_show_help(None) is None


def test_a_command_s_help_option_writes_through_show_help() -> None:
    result = CliRunner().invoke(app, ["state", "-h"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "Say where the repository stands now" in result.stdout
