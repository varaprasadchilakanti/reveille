# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A note that changes how a negative answer reads is given with it.

`repos` said "No Git repository found" (exit 1) when the only directory below
could not be listed, and dropped the note saying so; a shallow clone's empty
window was a plain "no" without the note that the clone holds only part of the
history.
"""

from __future__ import annotations

import os
import subprocess
import sys
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


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX modes that apply"
)
def test_nothing_found_beside_a_directory_that_cannot_be_listed_cannot_run(
    tmp_path: Path,
) -> None:
    hidden = tmp_path / "x"
    hidden.mkdir()
    hidden.chmod(0)
    try:
        result = CliRunner().invoke(app, ["repos", str(tmp_path)])
    finally:
        hidden.chmod(0o755)

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "1 directory could not be listed, and may hold one" in result.stderr


def test_nothing_found_where_everything_was_listed_is_a_negative_answer(tmp_path: Path) -> None:
    """Positive control: an empty directory is a true "no"."""
    (tmp_path / "x").mkdir()

    result = CliRunner().invoke(app, ["repos", str(tmp_path)])

    assert result.exit_code == ExitCode.NEGATIVE, result.stderr
    assert "could not be listed" not in result.stderr


@pytest.fixture
def shallow(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    _commit(source, "old.txt", "2026-01-10")
    _commit(source, "new.txt", "2026-04-10")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{source}", str(clone)], check=True
    )
    return clone


@pytest.mark.parametrize(
    "args",
    [
        ["summary"],
        ["brief", "--since", "2026-01-01"],
        ["who-changed", "new.txt"],
        ["generate", "-q", "-o", "-"],
    ],
)
def test_an_empty_window_in_a_shallow_clone_says_it_is_shallow(
    shallow: Path, args: list[str]
) -> None:
    result = CliRunner().invoke(app, [*args, "--repo", str(shallow), "--until", "2026-02-15"])

    assert result.exit_code == ExitCode.NEGATIVE, result.stderr
    assert "Note: This is a shallow clone, so only the history it holds is analysed." in (
        result.stderr
    )
