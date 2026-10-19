# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Git missing, or refusing your own configuration, is said as that, not as a defect."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


def _summary(
    tmp_path: Path, query: tuple[str, ...] = ("summary",), **env: str
) -> subprocess.CompletedProcess[str]:
    where = [str(tmp_path)] if query[0] == "repos" else ["--repo", str(tmp_path)]
    return subprocess.run(
        [sys.executable, "-c", _CHILD, *query, *where, "--format", "json"],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
    )


def _one_error(done: subprocess.CompletedProcess[str]) -> str:
    assert done.returncode == 2, done.stderr
    [line] = [json.loads(text) for text in done.stderr.splitlines()]
    assert line["level"] == "error", line
    assert "defect" not in line["message"], line
    return str(line["message"])


def test_no_git_on_path_is_said_plainly(tmp_path: Path) -> None:
    message = _one_error(_summary(tmp_path, PATH=str(tmp_path / "nowhere")))

    assert "Git could not be started" in message and "PATH" in message, message


@pytest.mark.parametrize(
    "query", [("summary",), ("brief",), ("state",), ("repos",), ("who-changed", "a.txt")]
)
def test_a_broken_global_git_configuration_is_named(tmp_path: Path, query: tuple[str, ...]) -> None:
    broken = tmp_path / "gitconfig"
    broken.write_text("[core\n", encoding="utf-8")

    message = _one_error(_summary(tmp_path, query, GIT_CONFIG_GLOBAL=str(broken)))

    assert "bad config line 1" in message, message
