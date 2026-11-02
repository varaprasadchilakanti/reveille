# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Output sent to a pipe or a file is UTF-8, whatever the locale's encoding.

Windows encodes a redirected stream in the locale's code page, cp1252 on most
machines. A name outside it stopped `who-changed`, and `generate -o -` as CSV or
HTML, with "This is a defect in Reveille". `PYTHONIOENCODING` sets the same
encoding here on every platform.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"
_NAME = "李雷 Ünïcode"


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("encoding") / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_bytes(b"a\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", f"user.name={_NAME}", "-c", "user.email=l@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "args",
    [
        ["who-changed", "a.txt"],
        ["generate", "--format", "csv", "-o", "-", "-q"],
        ["generate", "--format", "html", "-o", "-", "-q"],
        ["generate", "--format", "json", "-o", "-", "-q"],
    ],
)
def test_a_name_outside_the_code_page_reaches_a_pipe_as_utf8(repo: Path, args: list[str]) -> None:
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, *args, "--repo", str(repo)],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    out = done.stdout.decode("utf-8")
    assert _NAME in out or "\\u674e\\u96f7 \\u00dcn\\u00efcode" in out


def test_a_closed_stream_is_left_to_the_write_that_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reveille.cli import _write_utf8_where_not_a_terminal

    closed = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    closed.close()
    redirected = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", closed)
    monkeypatch.setattr(sys, "stderr", redirected)

    _write_utf8_where_not_a_terminal()

    assert closed.encoding == "cp1252"
    assert redirected.encoding == "utf-8"
