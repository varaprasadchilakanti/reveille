# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A `.mailmap` that is a FIFO, or a `mailmap.file` naming one, hangs nothing.

Git opens the mailmap itself when it applies one (`log.mailmap`, `%aN`, `%aE`),
and blocks reading a FIFO. Reveille parses `.mailmap` itself, so it switches
Git's own mailmap off. A copied directory or archive can carry a FIFO; `git
clone` cannot.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    run = {"cwd": path, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q", "-b", "main"], **run)  # type: ignore[call-overload]
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], **run)  # type: ignore[call-overload]
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"], **run
    )  # type: ignore[call-overload]
    subprocess.run(["git", "tag", "v1"], **run)  # type: ignore[call-overload]
    return path


def _run(repo: Path, *args: str) -> int:
    """Run the CLI in a child process with a timeout, so a hang fails the test."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "reveille", *args, "--repo", str(repo)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return -1
    return done.returncode


@pytest.mark.parametrize(
    "args", [("summary",), ("validate",), ("state",), ("brief",), ("who-changed", "a.txt")]
)
@pytest.mark.parametrize("where", ["working tree", "mailmap.file"])
def test_no_command_hangs(repo: Path, tmp_path: Path, args: tuple[str, ...], where: str) -> None:
    if where == "working tree":
        os.mkfifo(repo / ".mailmap")
    else:
        os.mkfifo(tmp_path / "fifo")
        subprocess.run(
            ["git", "config", "mailmap.file", str(tmp_path / "fifo")], cwd=repo, check=True
        )

    assert _run(repo, *args) in (0, 1), f"{' '.join(args)} hung or failed"
