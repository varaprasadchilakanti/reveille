# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The brief a closed window suggests next starts where that window ended.

With `--until`, the tip of the branch can be later than the window. The hint said
`--from <tip>`, and a caller who followed it never saw the commits in between.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _commit(repo: Path, name: str, day: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    when = {"GIT_AUTHOR_DATE": f"{day}T12:00:00Z", "GIT_COMMITTER_DATE": f"{day}T12:00:00Z"}
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", name],
        cwd=repo,
        check=True,
        env={**os.environ, **when},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    _commit(tmp_path, "september.txt", "2026-09-10")
    _commit(tmp_path, "october.txt", "2026-10-05")
    return tmp_path


def _next(output: str) -> list[str]:
    [hint] = re.findall(r"^Next: `?(reveille [^`\n]+)`?$", output, re.MULTILINE)
    return shlex.split(hint)[1:]


@pytest.mark.parametrize("output_format", ["text", "markdown"])
def test_the_next_brief_after_a_closed_window_misses_nothing(
    repo: Path, output_format: str
) -> None:
    window = ["--since", "2026-09-01", "--until", "2026-09-30", "--format", output_format]
    first = CliRunner().invoke(app, ["brief", "--repo", str(repo), *window])
    assert first.exit_code == ExitCode.SUCCESS, first.stderr

    following = _next(first.stdout)
    assert following == ["brief", "--since", "2026-10-01"]

    second = CliRunner().invoke(app, [*following, "--repo", str(repo), "--format", "json"])
    assert second.exit_code == ExitCode.SUCCESS, second.stderr
    assert '"commits": 1' in second.stdout


def test_an_open_window_continues_from_the_tip(repo: Path) -> None:
    tip = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    result = CliRunner().invoke(app, ["brief", "--repo", str(repo), "--since", "2026-09-01"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert _next(result.stdout) == ["brief", "--from", tip[:12]]
