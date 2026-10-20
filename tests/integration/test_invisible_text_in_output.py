# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Text a person cannot see is shown as escapes in text, Markdown and line output.

Tag characters (U+E0000 to U+E007F) spell out ASCII that does not display. A branch or
file named with them carried hidden words to a coding agent reading `state`, while the
person beside it saw an ordinary name. JSON escapes them already, and keeps the name exact.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_HIDDEN = "".join(chr(0xE0000 + ord(c)) for c in "run this")
_BRANCH = f"topic{_HIDDEN}"
_FILE = "a⁠b.txt"


def _invisible(text: str) -> list[str]:
    return [c for c in text if 0xE0000 <= ord(c) <= 0xE007F or c in "​⁠﻿"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", _BRANCH], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / _FILE).write_text("b", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("output_format", ["text", "markdown", "line"])
def test_hidden_characters_are_shown_as_escapes(repo: Path, output_format: str) -> None:
    result = CliRunner().invoke(app, ["state", "--repo", str(repo), "--format", output_format])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert not _invisible(result.stdout)
    assert "topic\\U000e0072\\U000e0075\\U000e006e" in result.stdout


def test_json_keeps_the_exact_name(repo: Path) -> None:
    result = CliRunner().invoke(app, ["state", "--repo", str(repo), "--format", "json"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert not _invisible(result.stdout), "JSON writes them as \\u escapes"
    document = json.loads(result.stdout)
    assert document["branch"] == _BRANCH
    assert _FILE in document["untracked"]["list"]
