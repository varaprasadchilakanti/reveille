# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""An answer that cannot be delivered on stdout is never reported as delivered.

Exit 1 is the negative answer and 0 a delivered one, so a full disk, a closed
stdout and a reader that stopped early each need their own, honest, outcome.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX file descriptors and /dev/full"),
]

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="needs /dev/full")
@pytest.mark.parametrize(
    "args", [["summary"], ["state", "--format", "json"], ["generate", "--output", "-", "-q"]]
)
def test_a_full_disk_on_stdout_cannot_run(repo: Path, args: list[str]) -> None:
    with open("/dev/full", "w") as full:
        done = subprocess.run(
            [sys.executable, "-c", _CHILD, *args, "--repo", str(repo)],
            stdout=full,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    assert done.returncode == 2, done.stderr
    assert "could not be written to standard output" in done.stderr, done.stderr
    assert "defect" not in done.stderr and "Exception ignored" not in done.stderr, done.stderr


def test_a_closed_stdout_cannot_run(repo: Path) -> None:
    done = subprocess.run(
        [
            "sh",
            "-c",
            'exec "$@" >&-',
            "sh",
            sys.executable,
            "-c",
            _CHILD,
            "summary",
            "-r",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2, done.stderr
    assert "standard output is closed" in done.stderr, done.stderr


def test_a_reader_that_stops_early_is_not_a_negative_answer(repo: Path) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, "generate", "--output", "-", "-q", "--repo", str(repo)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert child.stdout is not None and child.stderr is not None
    assert child.stdout.read(1), "positive control: the report started"
    child.stdout.close()
    error = child.stderr.read().decode()
    child.wait(timeout=60)

    assert child.returncode == 0, error
    assert "Traceback" not in error and "defect" not in error, error


def test_a_report_written_to_a_file_is_delivered_with_stdout_closed(repo: Path) -> None:
    out = repo / "r.html"
    done = subprocess.run(
        [
            *("sh", "-c", 'exec "$@" >&-', "sh", sys.executable, "-c", _CHILD),
            *("generate", "-q", "--repo", str(repo), "--output", str(out)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert out.stat().st_size > 0


_HELP_FORMS = [
    [],
    ["help"],
    ["help", "summary"],
    ["--help"],
    ["summary", "--help"],
    ["state", "-h"],
]


def _help_code(args: list[str]) -> int:
    """A bare `reveille` is not a command, so its help is given with exit 2."""
    return 2 if not args else 0


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="needs /dev/full")
@pytest.mark.parametrize("args", _HELP_FORMS)
def test_help_on_a_full_disk_cannot_run(args: list[str]) -> None:
    with open("/dev/full", "w") as full:
        done = subprocess.run(
            [sys.executable, "-c", _CHILD, *args],
            stdout=full,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    assert done.returncode == 2, done.stderr
    assert "could not be written to standard output" in done.stderr, done.stderr
    assert "defect" not in done.stderr and "Exception ignored" not in done.stderr, done.stderr


@pytest.mark.parametrize("args", _HELP_FORMS)
def test_help_on_a_closed_stdout_cannot_run(args: list[str]) -> None:
    done = subprocess.run(
        ["sh", "-c", 'exec "$@" >&-', "sh", sys.executable, "-c", _CHILD, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2, done.stderr
    assert "standard output is closed" in done.stderr, done.stderr


@pytest.mark.parametrize("args", _HELP_FORMS)
def test_help_to_a_reader_that_stopped_is_not_a_negative_answer(args: list[str]) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert child.stdout is not None and child.stderr is not None
    child.stdout.close()  # before the interpreter has started, so every write fails
    error = child.stderr.read().decode()
    child.wait(timeout=60)

    assert child.returncode == _help_code(args), error
    assert "Traceback" not in error and "defect" not in error, error


@pytest.mark.parametrize("args", _HELP_FORMS)
def test_help_is_delivered_with_its_exit_code(args: list[str]) -> None:
    """Positive control for the three above."""
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, *args], capture_output=True, text=True, check=False
    )

    assert done.returncode == _help_code(args), done.stderr
    # Rich colours help on CI (GITHUB_ACTIONS), so the codes are taken out first.
    assert "Usage: reveille" in re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="needs /dev/full")
def test_a_report_written_to_a_file_is_delivered_with_stdout_full(repo: Path) -> None:
    """The path printed after it is a confirmation, left out as with a closed stdout."""
    out = repo / "r.html"
    with open("/dev/full", "w") as full:
        done = subprocess.run(
            [sys.executable, "-c", _CHILD, "generate", "-q", "--repo", str(repo), "-o", str(out)],
            stdout=full,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    assert done.returncode == 0, done.stderr
    assert out.stat().st_size > 0


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="needs /dev/full")
def test_a_defect_with_output_buffered_for_a_full_disk_exits_2(repo: Path) -> None:
    """The interpreter's last flush of that output once turned the exit into 120."""
    child = (
        "import sys; import reveille.cli as cli; import reveille.services.report as report\n"
        "def boom(*args, **kwargs):\n"
        "    sys.stdout.write('buffered')\n"
        "    raise RuntimeError('boom')\n"
        "report.summary_text = boom\n"
        "sys.argv = ['reveille', *sys.argv[1:]]; cli.app()\n"
    )
    with open("/dev/full", "w") as full:
        done = subprocess.run(
            [sys.executable, "-c", child, "summary", "--repo", str(repo)],
            stdout=full,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    assert done.returncode == 2, done.stderr
    assert "RuntimeError: boom. This is a defect" in done.stderr
    assert "Exception ignored" not in done.stderr, done.stderr
