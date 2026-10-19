# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Each refusal names its own cause, not another one, and never "a defect in Reveille"."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "a"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


def _refused(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    assert "defect" not in result.stderr, result.stderr
    return result.stderr


def test_the_git_directory_given_as_the_repository(repo: Path) -> None:
    said = _refused("summary", "--repo", str(repo / ".git"))

    assert "is the Git directory of the working tree" in said and "core.worktree" not in said


@pytest.mark.parametrize("option", ["--from", "--branch"])
def test_an_empty_revision(repo: Path, option: str) -> None:
    window = [] if option == "--from" else ["--since", "2000-01-01"]
    said = _refused("brief", option, "", *window, "--repo", str(repo))

    assert "empty revision" in said and "beginning with '-'" not in said, said


def test_an_output_name_too_long_for_the_system(repo: Path) -> None:
    said = _refused("generate", "-q", "--repo", str(repo), "-o", str(repo / ("a" * 300)))

    assert "cannot be used" in said, said


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")
@pytest.mark.parametrize("target", ["device", "pipe"])
def test_an_output_that_is_not_a_file_is_left_alone(
    repo: Path, tmp_path: Path, target: str
) -> None:
    if target == "device":
        path = Path(os.devnull)
    else:
        path = tmp_path / "pipe.html"
        os.mkfifo(path)

    said = _refused("generate", "-q", "--repo", str(repo), "-o", str(path))

    assert "not a regular file" in said and ".tmp" not in said, said
    assert not stat.S_ISREG(path.stat().st_mode)


def test_init_suggests_a_configuration_file_name(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)

    said = _refused("init", "-o", ".")

    assert "reveille.toml" in said and "report.html" not in said, said


def test_repos_given_a_repository_says_so(repo: Path) -> None:
    result = CliRunner().invoke(app, ["repos", str(repo)])

    assert result.exit_code == ExitCode.NEGATIVE, result.stderr
    assert "is a repository itself" in result.stderr, result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="a deleted current directory is POSIX")
def test_a_current_directory_that_was_deleted(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    done = subprocess.run(
        [
            *("sh", "-c", 'cd "$1" && rmdir "$1" && shift && exec "$@"', "sh", str(gone)),
            *(sys.executable, "-c", _CHILD, "summary"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2, done.stderr
    assert "current directory no longer exists" in done.stderr, done.stderr
