# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A bare repository whose `HEAD` is a link Git reads, and a tree that only looks like one.

With `HEAD` linked to a branch only `packed-refs` holds, Git reads the
repository; Reveille wrote a report into its `objects` and `repos` passed it
over. A directory holding files named `HEAD`, `objects` and `refs` was refused
as output, though Git does not take it for a repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not hasattr(os, "symlink"), reason="links"),
]


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args], cwd=cwd, check=True
    )


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    _git("init", "-q", "-b", "main", str(source))
    (source / "a.txt").write_text("a", encoding="utf-8")
    _git("add", "a.txt", cwd=source)
    _git("commit", "-qm", "a", cwd=source)
    path = tmp_path / "found" / "linked.git"
    _git("clone", "-q", "--bare", str(source), str(path))
    _git("pack-refs", "--all", cwd=path)
    (path / "HEAD").unlink()
    (path / "HEAD").symlink_to("refs/heads/main")
    assert not (path / "HEAD").exists(), "the link dangles: packed-refs holds the branch"
    return path


def test_git_reads_it(bare: Path) -> None:
    """Positive control: the layout is one Git accepts."""
    subprocess.run(["git", "-C", str(bare), "log", "-1"], check=True, capture_output=True)


def test_a_report_is_not_written_into_it(bare: Path) -> None:
    out = bare / "objects" / "r.html"

    result = CliRunner().invoke(app, ["generate", "-q", "--repo", str(bare), "-o", str(out)])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.output
    assert "inside a Git directory" in result.stderr
    assert not out.exists()


def test_repos_finds_it(bare: Path) -> None:
    result = CliRunner().invoke(app, ["repos", str(bare.parent), "--format", "json"])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert '"linked.git"' in result.stdout


def test_a_tree_that_only_looks_like_one_is_written_into(bare: Path, tmp_path: Path) -> None:
    lookalike = tmp_path / "notes"
    for name in ("objects", "refs"):
        (lookalike / name).mkdir(parents=True)
    (lookalike / "HEAD").write_text("Things to do at the start of the day.\n", encoding="utf-8")
    out = lookalike / "objects" / "r.html"

    result = CliRunner().invoke(app, ["generate", "-q", "--repo", str(bare), "-o", str(out)])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert out.is_file()
