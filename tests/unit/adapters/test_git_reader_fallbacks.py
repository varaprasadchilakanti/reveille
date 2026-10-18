# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""What the reader does when Git is older or fails, which Git 2.55 here never does."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from git.exc import GitCommandError

from reveille.adapters.git_reader import GitReader
from reveille.exceptions import RepositoryError

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


class _Runner:
    """Stands in for `GitReader._git()`; `fail` names commands that raise."""

    def __init__(self, real: Any, fail: dict[str, int], worktrees: str = "") -> None:
        self._real, self._fail, self._worktrees = real, fail, worktrees

    def __getattr__(self, command: str) -> Any:
        def call(*args: str) -> Any:
            key = command if command != "worktree" else f"worktree{'-z' if '-z' in args else ''}"
            if key in self._fail:
                raise GitCommandError(command, self._fail[key])
            if command == "worktree":
                return self._worktrees
            return getattr(self._real, command)(*args)

        return call


def test_old_git_lists_worktrees_without_z(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = GitReader(repo)
    real = reader._git()
    records = "worktree /r\nHEAD 1\nbranch refs/heads/main\n\nworktree /w\ndetached\n"
    monkeypatch.setattr(
        reader, "_git", lambda extra=(): _Runner(real, {"worktree-z": 129}, records)
    )

    assert [w.path for w in reader._worktrees()] == ["/r", "/w"]


def test_worktrees_that_cannot_be_listed_are_none(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(
        reader, "_git", lambda extra=(): _Runner(real, {"worktree-z": 129, "worktree": 128})
    )

    assert reader._worktrees() == []


def test_an_unreadable_git_version_is_none(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda extra=(): _Runner(real, {"version": 1}))

    assert reader._git_version() is None
    assert reader._supports_since_as_filter() is False


def test_a_rev_parse_failure_other_than_ownership_cannot_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_git(self: GitReader, extra: Any = ()) -> Any:
        return _Runner(self._repo.git, {"rev_parse": 128})

    monkeypatch.setattr(GitReader, "_git", failing_git)

    with pytest.raises(RepositoryError, match="Git cannot read"):
        GitReader(repo)


@pytest.mark.parametrize("failing", ["status", "for_each_ref"])
def test_a_git_failure_in_state_is_reported_as_git_s(
    repo: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """Not as "a defect in Reveille": a corrupt index or a lock is the repository's."""
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda extra=(): _Runner(real, {failing: 128}))

    with pytest.raises(RepositoryError, match="Git could not read"):
        reader.read_state()


def test_a_tag_listing_failure_is_reported_as_git_s(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda extra=(): _Runner(real, {"rev_list": 128}))

    with pytest.raises(RepositoryError, match="Git could not list the tags"):
        reader.tags_in_range(None, None, None, None)


class _LogFails:
    """Stands in for `GitReader._git()`; a `git log` whose format matches raises."""

    def __init__(self, real: Any, marker: str) -> None:
        self._real, self._marker = real, marker

    def __getattr__(self, command: str) -> Any:
        def call(*args: str) -> Any:
            if command == "log" and any(self._marker in arg for arg in args):
                raise GitCommandError(command, 128)
            return getattr(self._real, command)(*args)

        return call


@pytest.mark.parametrize("marker", ["%an%x1f%ae", "trailers:key=Co-authored-by"])
def test_an_exclusion_whose_history_cannot_be_read_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    """Either query failing would apply the exclusion to part of the history."""
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda extra=(): _LogFails(real, marker))

    with pytest.raises(RepositoryError, match="cannot be applied in full"):
        reader.read_commits(None, None, None, ["a@e.test"])


def test_without_an_exclusion_the_history_is_not_read_for_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda extra=(): _LogFails(real, "%an%x1f%ae"))

    assert len(reader.read_commits(None, None, None, [])) == 1


def test_unreadable_noreply_addresses_are_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without them an account splits in two and a noreply exclusion misses one half."""
    reader = GitReader(repo)
    real = reader._git()
    monkeypatch.setattr(reader, "_git", lambda extra=(): _LogFails(real, "--format=%ae"))

    with pytest.raises(RepositoryError, match="author addresses"):
        reader.read_commits(None, None, None, [])
