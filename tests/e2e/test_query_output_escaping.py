# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""What `summary` and `who-changed` print cannot drive the terminal.

Their stdout is what an assistant or a person reads, and it carries text the
repository chose: its directory name, author names from a `.mailmap`. The
escaping added in 0.9.0 covered stderr only, so the red team (2026-10-12) got
an OSC 8 hyperlink, a bell and a carriage return onto stdout from a
directory name, and a C1 control sequence introducer and an Arabic letter
mark from a `.mailmap` name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

_CONTROL = ("\x1b", "\x07", "\r", "\x9b", "؜", "‎", "‏")


def _repo(path: Path, mailmap: str = "") -> Path:
    path.mkdir(parents=True)
    run = {"cwd": path, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q", "-b", "main"], **run)  # type: ignore[call-overload]
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    if mailmap:
        (path / ".mailmap").write_text(mailmap, encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], **run)  # type: ignore[call-overload]
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "x"],
        **run,  # type: ignore[call-overload]
    )
    return path


@pytest.mark.e2e
def test_a_directory_name_cannot_drive_the_terminal(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "term\x1b]8;;file:x\x07LINK\x1b]8;;\x07\rOVER")

    result = CliRunner().invoke(app, ["summary", "--repo", str(repo)])

    assert result.exit_code == ExitCode.SUCCESS
    assert "LINK" in result.stdout, "positive control: the name is printed"
    assert not [c for c in _CONTROL if c in result.stdout], repr(result.stdout)


@pytest.mark.e2e
def test_a_mailmap_name_cannot_drive_the_terminal(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r", "Mal\x9b2J؜Name‎ <a@e.test>\n")

    result = CliRunner().invoke(app, ["who-changed", "a.txt", "--repo", str(repo)])

    assert result.exit_code == ExitCode.SUCCESS
    assert "Mal" in result.stdout, "positive control: the name is printed"
    assert not [c for c in _CONTROL if c in result.stdout], repr(result.stdout)


@pytest.mark.e2e
def test_json_output_still_parses(tmp_path: Path) -> None:
    import json

    repo = _repo(tmp_path / "r", "Mal\x9b2J؜Name <a@e.test>\n")

    result = CliRunner().invoke(
        app, ["who-changed", "a.txt", "--repo", str(repo), "--format", "json"]
    )

    assert result.exit_code == ExitCode.SUCCESS
    names = [p["name"] for p in json.loads(result.stdout)["authors"]["list"]]
    assert names and names[0].startswith("Mal")
