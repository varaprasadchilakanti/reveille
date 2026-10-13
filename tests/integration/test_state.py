# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`reveille state`: where a repository stands now, changing nothing (ADR 0024)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_WHO = {
    "GIT_AUTHOR_NAME": "Ana Silva",
    "GIT_AUTHOR_EMAIL": "ana@e.test",
    "GIT_COMMITTER_NAME": "Ana Silva",
    "GIT_COMMITTER_EMAIL": "ana@e.test",
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *args],
        cwd=repo,
        env={**os.environ, **_WHO},
        check=check,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"change {path}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _commit(path, "a.txt", "one\n")
    _commit(path, "b.txt", "two\n")
    return path


def _state(repo: Path, *args: str) -> dict:
    result = CliRunner().invoke(app, ["state", "--repo", str(repo), "--format", "json", *args])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return json.loads(result.stdout)


def _text(repo: Path) -> str:
    result = CliRunner().invoke(app, ["state", "--repo", str(repo)])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


class TestItChangesNothingAndRunsNothing:
    def test_the_index_is_not_rewritten(self, repo: Path) -> None:
        """A plain `git status` rewrites the index when stat data is stale."""
        time.sleep(1.1)
        for name in ("a.txt", "b.txt"):
            os.utime(repo / name)
        index = repo / ".git" / "index"
        before = hashlib.sha256(index.read_bytes()).hexdigest()

        _state(repo)

        assert hashlib.sha256(index.read_bytes()).hexdigest() == before
        _git(repo, "status", "--porcelain")
        assert hashlib.sha256(index.read_bytes()).hexdigest() != before, (
            "positive control: plain git status does rewrite it here"
        )

    def test_a_repositorys_fsmonitor_program_does_not_run(self, repo: Path, tmp_path: Path) -> None:
        marker = tmp_path / "ran"
        hook = tmp_path / "hook.sh"
        hook.write_text(f"#!/bin/sh\necho ran > '{marker}'\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        _git(repo, "config", "core.fsmonitor", str(hook))

        _state(repo)

        assert not marker.exists()
        _git(repo, "status", "--porcelain", check=False)
        assert marker.exists(), "positive control: plain git status runs it"


class TestContentFilters:
    """`git status` runs a clean or process filter to compare a file; a repository's own
    config can name any program as one (measured 2026-10-12, Git 2.55)."""

    def _filtered(self, repo: Path, tmp_path: Path, key: str) -> Path:
        marker = tmp_path / "ran"
        program = tmp_path / "filter.sh"
        program.write_text(f"#!/bin/sh\necho ran >> '{marker}'\ncat\n", encoding="utf-8")
        program.chmod(0o755)
        (repo / ".gitattributes").write_text("*.txt filter=evil\n", encoding="utf-8")
        _git(repo, "config", f"filter.evil.{key}", str(program))
        time.sleep(1.1)
        os.utime(repo / "a.txt")
        return marker

    @pytest.mark.parametrize("key", ["clean", "process"])
    def test_a_filter_the_repository_names_does_not_run(
        self, repo: Path, tmp_path: Path, key: str
    ) -> None:
        marker = self._filtered(repo, tmp_path, key)

        state = _state(repo)

        assert not marker.exists()
        assert state["filters_not_run"] == ["evil"]
        assert "Not run: the content filters" in _text(repo)
        _git(repo, "status", "--porcelain", check=False)
        assert marker.exists(), "positive control: plain git status runs it"

    def test_a_filter_in_the_users_own_config_is_respected(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marker = tmp_path / "ran"
        program = tmp_path / "filter.sh"
        program.write_text(f"#!/bin/sh\necho ran >> '{marker}'\ncat\n", encoding="utf-8")
        program.chmod(0o755)
        own = tmp_path / "own.gitconfig"
        own.write_text(f'[filter "mine"]\n\tclean = {program}\n', encoding="utf-8")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(own))
        (repo / ".gitattributes").write_text("*.txt filter=mine\n", encoding="utf-8")
        time.sleep(1.1)
        os.utime(repo / "a.txt")

        state = _state(repo)

        assert state["filters_not_run"] == []
        assert marker.exists(), "the user's own filter runs as they configured it"

    @pytest.mark.parametrize(("status", "expected"), [(1, ()), (129, None)])
    def test_no_match_is_none_found_and_a_failure_is_unknown(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, status: int, expected: object
    ) -> None:
        """Exit 1 from `git config --get-regexp` means no match; anything else, such as
        an old Git without `--show-scope`, must not be read as "no filters"."""
        from git.exc import GitCommandError

        from reveille.adapters.git_reader import GitReader

        class _Git:
            def config(self, *_args: str) -> str:
                raise GitCommandError("config", status)

        reader = GitReader(repo)
        monkeypatch.setattr(reader, "_git", lambda extra=(): _Git())

        assert reader._repository_filters() == expected

    def test_when_scopes_cannot_be_known_no_file_is_compared(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from reveille.adapters.git_reader import GitReader

        monkeypatch.setattr(GitReader, "_repository_filters", lambda self: None)
        (repo / "new.txt").write_text("n\n", encoding="utf-8")

        state = _state(repo)

        assert state["working_tree_read"] is False
        assert state["untracked"]["total"] == 0
        assert state["branch"] == "main"
        assert "Working tree: not compared." in _text(repo)


class TestTheWorkingTree:
    def test_a_clean_tree(self, repo: Path) -> None:
        state = _state(repo)

        assert state["clean"] is True
        assert state["branch"] == "main"
        assert "Working tree: clean." in _text(repo)

    def test_each_kind_of_change(self, repo: Path) -> None:
        (repo / "staged.txt").write_text("s\n", encoding="utf-8")
        _git(repo, "add", "staged.txt")
        (repo / "a.txt").write_text("changed\n", encoding="utf-8")
        (repo / "b.txt").unlink()
        (repo / "new.txt").write_text("n\n", encoding="utf-8")

        state = _state(repo)

        assert state["staged"]["list"] == ["staged.txt"]
        assert state["modified"]["list"] == ["a.txt"]
        assert state["deleted"]["list"] == ["b.txt"]
        assert state["untracked"]["list"] == ["new.txt"]
        assert state["clean"] is False

    def test_a_rename(self, repo: Path) -> None:
        _git(repo, "mv", "a.txt", "renamed.txt")

        assert _state(repo)["renamed"]["list"] == ["renamed.txt"]

    def test_a_renamed_files_old_name_is_not_read_as_an_entry(self, repo: Path) -> None:
        """Git follows a rename entry with the old path; one shaped like an entry
        ("? ghost.txt") would otherwise appear as an untracked file."""
        _commit(repo, "? ghost.txt", "a file name a parser could mistake\n" * 5)
        _git(repo, "mv", "? ghost.txt", "real.txt")

        state = _state(repo)

        assert state["renamed"]["list"] == ["real.txt"]
        assert state["untracked"]["total"] == 0, state["untracked"]

    def test_lists_are_bounded(self, repo: Path) -> None:
        for i in range(15):
            (repo / f"u{i:02d}.txt").write_text("x\n", encoding="utf-8")

        state = _state(repo, "--limit", "3")

        assert state["untracked"]["total"] == 15
        assert state["untracked"]["truncated"] is True
        assert len(state["untracked"]["list"]) == 3
        assert "and 5 more" in _text(repo), "the text form bounds at its default of 10"

    def test_a_file_name_cannot_drive_the_terminal(self, repo: Path) -> None:
        (repo / "x\x1b]8;;y\x07z.txt").write_text("x\n", encoding="utf-8")
        out = _text(repo)

        assert "z.txt" in out
        assert "\x1b" not in out and "\x07" not in out


class TestWorkInProgress:
    def test_a_merge_stopped_on_a_conflict(self, repo: Path) -> None:
        _git(repo, "switch", "-q", "-c", "topic")
        _commit(repo, "a.txt", "topic\n")
        _git(repo, "switch", "-q", "main")
        _commit(repo, "a.txt", "main\n")
        _git(repo, "merge", "topic", check=False)

        state = _state(repo)

        assert state["operation_in_progress"] == "merge"
        assert state["conflicted"]["list"] == ["a.txt"]
        assert "In progress: merge." in _text(repo)

    def test_a_rebase_stopped_on_a_conflict(self, repo: Path) -> None:
        _git(repo, "switch", "-q", "-c", "topic")
        _commit(repo, "a.txt", "topic\n")
        _git(repo, "switch", "-q", "main")
        _commit(repo, "a.txt", "main\n")
        _git(repo, "switch", "-q", "topic")
        _git(repo, "rebase", "main", check=False)

        assert _state(repo)["operation_in_progress"] == "rebase"

    def test_stashes_are_counted(self, repo: Path) -> None:
        for text in ("x\n", "y\n"):
            (repo / "a.txt").write_text(text, encoding="utf-8")
            _git(repo, "stash", "push", "-q")

        assert _state(repo)["stashes"] == 2


class TestBranchesAndWorktrees:
    def test_another_worktree_is_listed(self, repo: Path, tmp_path: Path) -> None:
        _git(repo, "worktree", "add", "-q", "-b", "side", str(tmp_path / "wt"))

        state = _state(repo)

        assert state["worktrees_total"] == 2
        assert state["worktrees"][1]["branch"] == "side"

    def test_branches_are_counted_not_named(self, repo: Path) -> None:
        _git(repo, "branch", "jsmith/old-idea")
        _git(repo, "switch", "-q", "-c", "unmerged")
        _commit(repo, "c.txt", "c\n")
        _git(repo, "switch", "-q", "main")

        state = _state(repo)

        assert state["branches"] == {
            "local": 3,
            "merged_into_head": 2,
            "quiet": 0,
            "quiet_days": 90,
        }
        assert "jsmith" not in json.dumps(state) and "jsmith" not in _text(repo)

    def test_a_detached_head(self, repo: Path) -> None:
        _git(repo, "switch", "-q", "--detach", "HEAD~1")

        state = _state(repo)

        assert state["branch"] is None
        assert _text(repo).splitlines()[0].startswith("r: detached")

    def test_upstream_ahead_and_behind_as_of_the_last_fetch(
        self, repo: Path, tmp_path: Path
    ) -> None:
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
        _commit(clone, "mine.txt", "m\n")
        _commit(repo, "theirs.txt", "t\n")
        _git(clone, "fetch", "-q")

        upstream = _state(clone)["upstream"]

        assert upstream == {"name": "origin/main", "ahead": 1, "behind": 1, "as_of": "last fetch"}

    def test_the_latest_tag_and_the_next_command(self, repo: Path) -> None:
        _git(repo, "tag", "v1.0", "HEAD~1")

        state = _state(repo)

        assert (state["latest_tag"], state["commits_since_tag"]) == ("v1.0", 1)
        assert "Next: reveille brief --from v1.0" in _text(repo)

    def test_a_tag_named_like_an_option_writes_no_file(self, repo: Path) -> None:
        # A valid ref name a clone can bring; as an option it would make rev-list write a file.
        _git(repo, "update-ref", "refs/tags/--output=pwned", "HEAD~1")

        state = _state(repo)

        assert list(repo.glob("pwned*")) == []
        assert (state["latest_tag"], state["commits_since_tag"]) == ("--output=pwned", 1)


class TestUnusualRepositories:
    def test_no_commits_yet(self, tmp_path: Path) -> None:
        path = tmp_path / "empty"
        path.mkdir()
        _git(path, "init", "-q", "-b", "main")
        (path / "f.txt").write_text("x\n", encoding="utf-8")

        result = CliRunner().invoke(app, ["state", "--repo", str(path)])

        assert result.exit_code == ExitCode.SUCCESS, result.stderr
        assert "no commits yet" in result.stdout
        assert "1 untracked" in result.stdout

    def test_a_bare_repository(self, repo: Path, tmp_path: Path) -> None:
        bare = tmp_path / "b.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True)

        state = _state(bare)

        assert state["repository"]["bare"] is True
        assert state["branch"] == "main"
        assert "Bare repository" in _text(bare)

    def test_not_a_repository(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(app, ["state", "--repo", str(tmp_path)])

        assert result.exit_code == ExitCode.CANNOT_RUN
        assert result.stdout == ""


class TestItNamesNobodyAndStaysSmall:
    def test_no_author_in_any_form(self, repo: Path) -> None:
        for out in (json.dumps(_state(repo)), _text(repo)):
            assert "Ana" not in out and "ana@" not in out

    def test_the_text_is_under_two_kilobytes(self, repo: Path) -> None:
        for i in range(40):
            (repo / f"a-rather-long-directory-name-{i:02d}.txt").write_text("x\n", encoding="utf-8")

        assert len(_text(repo).encode()) < 2048
