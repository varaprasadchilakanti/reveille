# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A repository's own Git settings do not change the figures.

Each setting below, set in `.git/config`, changed what `git log --numstat` or
the trailer read reports (measured with Git 2.55): line counts doubled or
vanished, or co-authors disappeared. Reveille pins each to Git's default.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Ana",
    "GIT_AUTHOR_EMAIL": "ana@e.test",
    "GIT_COMMITTER_NAME": "Ana",
    "GIT_COMMITTER_EMAIL": "ana@e.test",
    "GIT_AUTHOR_DATE": "2026-01-01T10:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T10:00:00+00:00",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgSign=false", *args],
        cwd=repo,
        env=_ENV,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A root commit, a rename with edits, a file myers and histogram diff
    differently, and a commit crediting a co-author."""
    path = tmp_path_factory.mktemp("figures") / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    rng = random.Random(1)
    (path / "a.py").write_text("".join(f"line {i} {rng.random()}\n" for i in range(400)))
    (path / "big.txt").write_text("".join(f"row {i}\n" for i in range(20000)))
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "one")

    lines = (path / "a.py").read_text().splitlines(keepends=True)
    lines[100:100] = ["def x():\n", "    pass\n", "\n"]
    (path / "a.py").write_text("".join(lines))
    _git(path, "mv", "a.py", "b.py")
    _git(path, "commit", "-qam", "two")

    # Myers counts 7 and 7 for this change; histogram counts 10 and 10.
    (path / "f").write_text("\n".join("ddaceddcdceb"[i] for i in range(12)) + "\n")
    _git(path, "add", "f")
    _git(path, "commit", "-qm", "three")
    (path / "f").write_text("\n".join("ebcbaeceebca"[i] for i in range(12)) + "\n")
    _git(path, "commit", "-qam", "four\n\nCo-authored-by: Bea <bea@e.test>")
    return path


def _figures(repo: Path) -> tuple[int, int, int]:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", "json", "--output", "-", "-q"]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    report = json.loads(result.stdout)
    [ana] = report["contributors"]
    credited = sum(c["co_authored_commits"] for c in report["co_authors_only"])
    return ana["lines_added"], ana["lines_deleted"], credited


@pytest.mark.parametrize(
    "setting",
    [
        "diff.renames=false",
        "core.bigFileThreshold=1k",
        "log.showRoot=false",
        "diff.algorithm=histogram",
        "trailer.separators=#",
    ],
)
def test_a_repository_setting_leaves_the_figures_alone(repo: Path, setting: str) -> None:
    baseline = _figures(repo)
    key, value = setting.split("=", 1)
    _git(repo, "config", key, value)
    try:
        assert _figures(repo) == baseline
    finally:
        _git(repo, "config", "--unset", key)


def test_the_baseline_counts_the_root_commit_and_the_co_author(repo: Path) -> None:
    added, deleted, co_authored = _figures(repo)

    assert added > 20_400
    assert deleted < 50
    assert co_authored == 1
