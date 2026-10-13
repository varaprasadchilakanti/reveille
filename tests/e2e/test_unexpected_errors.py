# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""An error nobody anticipated exits 2, never 1.

Python exits 1 on an uncaught exception, and 1 is the contract's "ran, and the
answer is negative": a caller branching on it would take a crash for an answer.
Run in a real process, because the test runner bypasses the application's own
entry point.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from reveille.cli import ExitCode

_CRASH = """
import reveille.services.report as report
def boom(*args, **kwargs):
    raise RuntimeError("boom")
report.summary_text = boom
from reveille.cli import app
app(["summary", "--repo", "."], prog_name="reveille")
"""


@pytest.mark.e2e
def test_an_unexpected_exception_cannot_run() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CRASH], capture_output=True, text=True, check=False
    )

    assert result.returncode == ExitCode.CANNOT_RUN, result.stderr
    assert result.stdout == ""
    assert "RuntimeError: boom" in result.stderr
    assert "Traceback" not in result.stderr
