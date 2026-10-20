# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`repos` says how many directories it could not search, in a sentence that agrees."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions that bind"
    ),
]


@pytest.mark.parametrize("depth", ["1", "2"])
@pytest.mark.parametrize(
    ("locked", "said"),
    [
        (1, "1 directory could not be listed and was not searched."),
        (2, "2 directories could not be listed and were not searched."),
    ],
)
def test_the_count_and_the_verb_agree(tmp_path: Path, locked: int, said: str, depth: str) -> None:
    """At depth 1 a shut directory was left out silently; it may be a repository."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "a"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
    )
    shut = [tmp_path / f"shut{n}" for n in range(locked)]
    for directory in shut:
        directory.mkdir()
        directory.chmod(0)
    try:
        result = CliRunner().invoke(app, ["repos", str(tmp_path), "--depth", depth])
    finally:
        for directory in shut:
            directory.chmod(0o755)

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert said in result.stderr, result.stderr
