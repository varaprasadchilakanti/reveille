# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A file Git waits on stops Reveille at a deadline, wherever the file is.

The files Git reads first are checked before it runs, but Git opens many more:
loose refs and objects, the commit graph, alternates named by alternates. A
named pipe at any of them makes Git wait for ever. Every Git command Reveille
waits for has a deadline, and a history read that writes nothing for as long
is stopped. Here the deadline is cut to a few seconds.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reveille.adapters import git_reader
from reveille.exceptions import RepositoryError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX"),
]

_CHILD = (
    "import sys; from reveille.adapters import git_reader; git_reader.GIT_TIMEOUT_SECONDS = 3; "
    "from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"
)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    (path / "link-target").mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "a")
    return path


def _run(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run Reveille in a child; fail the test if it is still waiting after 20 seconds."""
    try:
        return subprocess.run(
            [sys.executable, "-c", _CHILD, *args, "--repo", str(repo)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Reveille waited on the pipe past its deadline")


def _git_waits(repo: Path, *args: str) -> bool:
    """Positive control: plain Git, given the same file, waits on it."""
    try:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return True
    return False


def _replace_with_pipe(path: Path) -> None:
    path.unlink()
    os.mkfifo(path)


def _refused(done: subprocess.CompletedProcess[str], name: str) -> None:
    assert done.returncode == 2, done.stderr
    assert name in done.stderr and "not a regular file" in done.stderr, done.stderr


def test_a_pipe_at_the_branchs_loose_ref(repo: Path) -> None:
    _replace_with_pipe(repo / ".git" / "refs" / "heads" / "main")

    assert _git_waits(repo, "log", "--numstat")
    _refused(_run(repo, "summary"), "refs/heads/main")


def test_a_pipe_at_the_commit_graph(repo: Path) -> None:
    os.mkfifo(repo / ".git" / "objects" / "info" / "commit-graph")

    assert _git_waits(repo, "log", "--numstat")
    _refused(_run(repo, "generate", "--format", "json", "--output", "-"), "commit-graph")


def test_a_pipe_at_an_alternates_file_an_alternate_names(repo: Path, tmp_path: Path) -> None:
    nested = tmp_path / "shared-objects"  # outside the repository, found only through alternates
    (nested / "info").mkdir(parents=True)
    (repo / ".git" / "objects" / "info" / "alternates").write_text(f"{nested}\n", encoding="utf-8")
    os.mkfifo(nested / "info" / "alternates")

    assert _git_waits(repo, "log", "--numstat")
    _refused(_run(repo, "summary"), "shared-objects/info/alternates")


def test_a_pipe_at_a_loose_object_the_history_read_needs(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    _replace_with_pipe(repo / ".git" / "objects" / head[:2] / head[2:])

    assert _git_waits(repo, "log", "--numstat")
    _refused(_run(repo, "generate", "--format", "json", "--output", "-"), head[2:])


def test_a_pipe_in_an_object_directory_reached_through_a_link(repo: Path, tmp_path: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    linked = repo / ".git" / "objects" / head[:2]
    moved = tmp_path / "moved-objects"
    linked.rename(moved)
    linked.symlink_to(moved, target_is_directory=True)
    _replace_with_pipe(moved / head[2:])

    assert _git_waits(repo, "log", "--numstat")
    _refused(_run(repo, "summary"), head[2:])


def test_a_loop_of_links_under_refs_does_not_hold_the_check(repo: Path) -> None:
    (repo / ".git" / "refs" / "heads" / "loop").symlink_to("..", target_is_directory=True)
    (repo / ".git" / "refs" / "heads" / "self").symlink_to("self")

    done = _run(repo, "summary", "--format", "json")

    assert done.returncode == 0, done.stderr


def test_a_pipe_behind_a_link_to_a_directory_is_refused(repo: Path, tmp_path: Path) -> None:
    """The walk for `.gitattributes` does not follow links; Git does."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.mkfifo(elsewhere / ".gitattributes")
    (repo / "link").symlink_to(elsewhere, target_is_directory=True)
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-qm", "x")
    _git(repo, "mv", "x.txt", "moved.txt")  # the history now names a path beside the link
    _git(repo, "commit", "-qm", "moved")
    subprocess.run(["git", "rm", "-q", "--cached", "-r", "link"], cwd=repo, check=False)

    done = _run(repo, "generate", "--format", "json", "--output", "-")

    assert done.returncode == 2, done.stderr
    assert "link/.gitattributes" in done.stderr and "not a regular file" in done.stderr


def test_a_relative_attributes_file_is_found_from_another_directory(
    repo: Path, tmp_path: Path
) -> None:
    os.mkfifo(repo / "attrs")
    _git(repo, "config", "core.attributesFile", "attrs")
    away = tmp_path / "away"
    away.mkdir()

    done = _run(repo, "generate", "--format", "json", "--output", "-", cwd=away)

    assert done.returncode == 2, done.stderr
    assert "attrs" in done.stderr and "not a regular file" in done.stderr


class TestTheDeadline:
    """Where no check reaches, the deadline stops Git: `hash-object` reads a pipe for ever."""

    def test_a_command_waited_for_is_stopped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.mkfifo(tmp_path / "pipe")
        monkeypatch.setattr(git_reader, "GIT_TIMEOUT_SECONDS", 2)
        started = time.monotonic()

        with pytest.raises(RepositoryError, match="within 2 seconds"):
            git_reader._TimedGit().execute(["git", "hash-object", str(tmp_path / "pipe")])
        assert time.monotonic() - started < 15

    def test_a_read_that_writes_nothing_is_stopped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.mkfifo(tmp_path / "pipe")
        monkeypatch.setattr(git_reader, "GIT_TIMEOUT_SECONDS", 2)
        process = git_reader._TimedGit().execute(
            ["git", "hash-object", str(tmp_path / "pipe")], as_process=True
        )
        started = time.monotonic()

        with pytest.raises(RepositoryError, match="within 2 seconds"):
            git_reader._LogStream(process).raw_records()
        assert time.monotonic() - started < 15
