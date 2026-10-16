# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A `.mailmap` is untrusted input, and reading it is bounded.

Two properties. The line patterns must not backtrack quadratically: one
200 KB line of repeated `a <b` stays well inside the 1 MiB bound on a
committed `.mailmap`, so the pattern cost must be linear. And the working-tree
`.mailmap` is bounded like the committed one, not read whole.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.adapters.git_reader import _parse_mailmap_line
from reveille.cli import ExitCode, app


def _repo(path: Path, mailmap: str | bytes) -> Path:
    path.mkdir(parents=True)
    run = {"cwd": path, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q", "-b", "main"], **run)  # type: ignore[call-overload]
    for email in ("old@e.test", "new@e.test"):
        (path / "a.txt").write_text(email, encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], **run)  # type: ignore[call-overload]
        subprocess.run(
            ["git", "-c", "user.name=Ana", "-c", f"user.email={email}", "commit", "-qm", "x"],
            **run,  # type: ignore[call-overload]
        )
    target = path / ".mailmap"
    if isinstance(mailmap, bytes):
        target.write_bytes(mailmap)
    else:
        target.write_text(mailmap, encoding="utf-8")
    return path


def _summary(repo: Path) -> tuple[int, dict, str]:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--format", "json"])
    payload = json.loads(result.stdout) if result.exit_code == ExitCode.SUCCESS else {}
    return result.exit_code, payload, result.stderr


@pytest.mark.integration
class TestReadingIsBounded:
    def test_a_hostile_line_is_read_in_linear_time(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path / "r", "a <b " * 40_000 + "\nAna <new@e.test> <old@e.test>\n")

        started = time.monotonic()
        code, payload, _ = _summary(repo)
        elapsed = time.monotonic() - started

        assert code == ExitCode.SUCCESS
        assert elapsed < 5, f"{elapsed:.1f}s; the quadratic parser took about 44s"
        assert payload["totals"]["authors"] == 1, "the valid line after it still applies"

    def test_a_working_tree_mailmap_over_the_limit_is_not_read(self, tmp_path: Path) -> None:
        line = b"Ana <new@e.test> <old@e.test>\n"
        repo = _repo(tmp_path / "r", line + b"#" * (1_048_576 + 1))

        code, payload, stderr = _summary(repo)

        assert code == ExitCode.SUCCESS
        assert payload["totals"]["authors"] == 2, "the file was read"
        assert "over the 1,048,576-byte limit" in stderr

    def test_a_working_tree_mailmap_at_the_limit_is_read(self, tmp_path: Path) -> None:
        line = b"Ana <new@e.test> <old@e.test>\n"
        repo = _repo(tmp_path / "r", line + b"#" * (1_048_576 - len(line)))

        code, payload, _ = _summary(repo)

        assert code == ExitCode.SUCCESS
        assert payload["totals"]["authors"] == 1


@pytest.mark.integration
def test_spaces_before_the_commit_address_still_map(tmp_path: Path) -> None:
    """Three spaces before the commit address once made the line do nothing.
    Each line is now read as Git reads it (test_mailmap_git_parity.py).
    """
    line = "Ana <new@e.test>   <old@e.test>"
    assert _parse_mailmap_line(line) == ("Ana", "new@e.test", None, "old@e.test")

    code, payload, _ = _summary(_repo(tmp_path / "r", line + "\n"))

    assert code == ExitCode.SUCCESS
    assert payload["totals"]["authors"] == 1
