# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""SIGTERM while a report is written exits 143 and leaves no temporary file.

By default Python stops where it is, and the `.tmp` beside the output stays.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="POSIX signals"),
]

# The child terminates itself once the temporary file is written, before it is moved.
_CHILD = """
import os, signal, sys
import reveille.replacing as r
real = r.os.replace
def replace(*args, **kwargs):
    os.kill(os.getpid(), signal.SIGTERM)
    return real(*args, **kwargs)
r.os.replace = replace
{default}
from reveille.cli import app
sys.argv = ["reveille", *sys.argv[1:]]
app()
"""


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


def _generate(repo: Path, out: Path, default: str = "") -> int:
    child = _CHILD.format(default=default)
    args = [sys.executable, "-c", child, "generate", "-q", "--repo", str(repo), "-o", str(out)]
    return subprocess.run(args, capture_output=True, timeout=60, check=False).returncode


def test_sigterm_during_the_write_exits_143_with_no_temporary(repo: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    code = _generate(repo, out_dir / "r.html")

    assert code == 128 + signal.SIGTERM
    assert list(out_dir.iterdir()) == []


def test_without_the_handler_the_temporary_is_left(repo: Path, tmp_path: Path) -> None:
    """Positive control: a handler someone else set is kept, and this one is the default."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    keep_default = "import reveille.cli as c; c._exit_cleanly_on_sigterm = lambda: None"

    code = _generate(repo, out_dir / "r.html", default=keep_default)

    assert code == -signal.SIGTERM
    assert [p.suffix for p in out_dir.iterdir()] == [".tmp"]


def test_a_handler_already_installed_is_kept(repo: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ignore = "import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN)"

    code = _generate(repo, out_dir / "r.html", default=ignore)

    assert code == 0
    assert [p.name for p in out_dir.iterdir()] == ["r.html"]
