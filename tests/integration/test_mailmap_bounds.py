# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A `.mailmap` is untrusted input, and reading it is bounded.

Two defects, found by the 2026-10-12 red team. The four line patterns
backtracked quadratically, so one 200 KB line of `a <b a <b ...` took about
44 seconds, inside the 1 MiB bound on a committed `.mailmap`. And only the
committed file was bounded: a 66 MB working-tree `.mailmap` was read whole,
30 seconds and 517 MB.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.adapters.git_reader import _parse_mailmap_line
from reveille.cli import ExitCode, app

# The patterns the parser replaced, kept here as the reference it must agree with.
_OLD_FOUR = re.compile(r"^(.+?)\s+<([^>]+)>\s+(.+?)\s+<([^>]+)>$")
_OLD_THREE = re.compile(r"^(.+?)\s+<([^>]+)>\s+<([^>]+)>$")
_OLD_EMAIL = re.compile(r"^<([^>]+)>\s+<([^>]+)>$")
_OLD_NAME = re.compile(r"^(.+?)\s+<([^>]+)>$")


def _old(line: str) -> tuple[str, ...] | None:
    for pattern in (_OLD_FOUR, _OLD_THREE, _OLD_EMAIL, _OLD_NAME):
        found = pattern.match(line)
        if found:
            return found.groups()
    return None


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


_LINES = [
    "Ana Silva <ana@e.test>",
    "Ana Silva <ana@e.test> <old@e.test>",
    "<ana@e.test> <old@e.test>",
    "Ana Silva <ana@e.test> Old Name <old@e.test>",
    "Ana   Silva   <ana@e.test>    Old   Name    <old@e.test>",
    "Ana\t<ana@e.test>\t<old@e.test>",
    "Ana<ana@e.test>",
    "Ana <ana@e.test><old@e.test>",
    "<ana@e.test>",
    "Ana <>",
    "Ana <ana@e.test",
    "Ana <ana@e.test> trailing",
    "Ana <a <b@e.test>",
    "A>na <ana@e.test>",
    "Ana <ana@e.test> Old <old@e.test> x",
    "no address at all",
    "Ana  <ANA@E.TEST> <Old@E.Test>",
]


@pytest.mark.parametrize("line", _LINES)
def test_the_parser_agrees_with_the_patterns_it_replaced(line: str) -> None:
    assert _parse_mailmap_line(line) == _old(line)


@pytest.mark.parametrize(
    "line",
    [
        "<ana@e.test> Old <old@e.test>",
        "Ana <ana@e.test> <old@e.test> <third@e.test>",
        "a<b <c@e.test>",
        "Ana <ana@e.test>Old <old@e.test>",
    ],
)
def test_a_name_holding_an_address_is_malformed(line: str) -> None:
    """The old patterns read these with a "name" such as `<ana@e.test> Old`.

    Git takes a name to end at the first `<`, so no name holds one; the
    line is skipped, as every other malformed line is.
    """
    assert _old(line) is not None, "positive control: the old patterns accepted it"
    assert _parse_mailmap_line(line) is None


@pytest.mark.integration
def test_spaces_before_the_commit_address_still_map(tmp_path: Path) -> None:
    """With three spaces before the second `<`, the old four-field pattern
    matched first, took one space as the commit name, and keyed the rule on
    a name no commit has: the line silently did nothing.
    """
    line = "Ana <new@e.test>   <old@e.test>"
    assert _old(line) == ("Ana", "new@e.test", " ", "old@e.test"), "the old misreading"
    assert _parse_mailmap_line(line) == ("Ana", "new@e.test", "old@e.test")

    code, payload, _ = _summary(_repo(tmp_path / "r", line + "\n"))

    assert code == ExitCode.SUCCESS
    assert payload["totals"]["authors"] == 1
