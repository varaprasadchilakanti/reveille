# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Text Git hands over is split and read as Git reads it.

Python's `str.splitlines` also breaks at U+2028, U+0085, form feed and `\\x1c`-`\\x1e`; Git
breaks only at a line feed. Each test pairs Reveille's reading with Git's own.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from reveille.adapters import git_reader
from reveille.adapters.git_reader import (
    GitReader,
    _object_directories,
    _refuse_git_files_that_block,
    repository_root,
)
from reveille.cli import ExitCode, app
from reveille.exceptions import RepositoryError

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str, name: str = "Ana", email: str = "ana@e.test") -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "C",
        "GIT_COMMITTER_EMAIL": "c@e.test",
    }
    done = subprocess.run(
        ["git", *args], cwd=repo, check=True, env=env, capture_output=True, text=True
    )
    return done.stdout


def _commit(repo: Path, message: str, name: str = "Ana", email: str = "ana@e.test") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message, name=name, email=email)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "base")
    return path


def _json(repo: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", "json", "-o", "-", *args]
    )
    return result.exit_code, json.loads(result.stdout) if result.exit_code == 0 else {}


@pytest.mark.skipif(sys.platform != "linux", reason="needs a file system that keeps any byte")
def test_a_path_that_is_not_utf8_reads_with_quote_path_off(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / os.fsdecode(b"d\xff\xfe")).write_text("x\n", encoding="utf-8")
    _commit(repo, "odd name")
    settings = tmp_path / "global.cfg"
    settings.write_text("[core]\n\tquotePath = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
    # Positive control: with the setting, Git prints the raw byte.
    assert (
        b"\xff"
        in subprocess.run(
            ["git", "log", "--numstat", "--format="], cwd=repo, check=True, capture_output=True
        ).stdout
    )

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "-o", str(repo / "r.html")])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr


def test_a_mailmap_line_git_reads_as_a_comment_maps_no_one(repo: Path) -> None:
    (repo / "b").write_text("1\n", encoding="utf-8")
    _commit(repo, "victim", name="Vic", email="v@e.test")
    (repo / ".mailmap").write_text(
        "# aliases\u2028Mallory <m@e.test> <v@e.test>\n", encoding="utf-8"
    )
    _commit(repo, "mailmap")
    # Positive control: Git maps the address to itself.
    assert _git(repo, "check-mailmap", "<v@e.test>").strip() == "<v@e.test>"

    code, document = _json(repo)

    assert code == ExitCode.SUCCESS
    emails = {person["email"] for person in document["contributors"]}
    assert "v@e.test" in emails
    assert "m@e.test" not in emails


def test_a_mailmap_with_crlf_line_ends_still_maps(repo: Path) -> None:
    (repo / "b").write_text("1\n", encoding="utf-8")
    _commit(repo, "old address", name="Vic", email="old@e.test")
    (repo / ".mailmap").write_bytes(b"Vic <v@e.test> <old@e.test>\r\n")
    _commit(repo, "mailmap")
    assert _git(repo, "check-mailmap", "<old@e.test>").strip() == "Vic <v@e.test>"

    code, document = _json(repo)

    assert code == ExitCode.SUCCESS
    assert "v@e.test" in {person["email"] for person in document["contributors"]}


def test_no_readable_commit_cannot_run(tmp_path: Path) -> None:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "only", name="Ana\x1eX")
    # Positive control: Git kept the separator in the author name.
    assert "\x1e" in _git(path, "log", "--format=%an")

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(path), "--format", "json", "-o", "-"]
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "1 commit in the window could not be read" in result.stderr


def test_a_filter_that_leaves_only_unreadable_commits_cannot_run(tmp_path: Path) -> None:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "readable")
    (path / "a").write_text("2\n", encoding="utf-8")
    _commit(path, "unreadable", name="Bo\x1eX")

    result = CliRunner().invoke(
        app,
        [
            *("generate", "--repo", str(path), "--format", "json", "-o", "-"),
            *("--exclude-author", "ana@e.test"),
        ],
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "No commit was counted" in result.stderr
    assert "Try removing an --exclude-author value." in result.stderr


def test_an_exclusion_is_not_a_branch(repo: Path) -> None:
    # Positive control: Git accepts it as a revision.
    assert _git(repo, "rev-parse", "--verify", "^main").startswith("^")

    code, _ = _json(repo, "--branch", "^main")

    assert code == ExitCode.CANNOT_RUN


def test_an_excluded_path_keeps_its_leading_space(repo: Path) -> None:
    for directory, name, email in ((" sp", "Spa", "spa@e.test"), ("sp", "Bob", "bob@e.test")):
        (repo / directory).mkdir()
        (repo / directory / "f").write_text("1\n", encoding="utf-8")
        _commit(repo, directory, name=name, email=email)

    code, document = _json(repo, "--exclude-path", " sp")

    assert code == ExitCode.SUCCESS
    emails = {person["email"] for person in document["contributors"]}
    assert "spa@e.test" not in emails
    assert "bob@e.test" in emails


def test_an_unmatched_path_is_quoted_so_its_spaces_show(repo: Path) -> None:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--exclude-path", "a "])

    assert result.exit_code == ExitCode.SUCCESS
    assert "'a '" in result.stderr


def test_a_branch_name_with_an_odd_space_is_one_branch(repo: Path) -> None:
    _git(repo, "branch", "feature\u00a0one")
    _git(repo, "branch", "a\u2028b")
    _git(repo, "branch", "a\u2028c")

    state = GitReader(repo).read_state()

    assert state.branches == 4
    assert state.branches_merged == 4


def test_a_tag_name_with_a_line_separator_is_listed_whole(repo: Path) -> None:
    (repo / "a").write_text("2\n", encoding="utf-8")
    _commit(repo, "second")
    _git(repo, "tag", "v1\u2028rc")

    tags = GitReader(repo).tags_in_range(branch=None, from_commit=None, since=None, until=None)

    assert tags == ["v1\u2028rc"]


@pytest.mark.skipif(sys.platform == "win32", reason="a Windows file name cannot hold '>'")
@pytest.mark.xfail(strict=True, reason="TODO(git-read): numstat without -z prints both alike")
def test_a_directory_named_like_a_rename_is_its_own_path(repo: Path) -> None:
    (repo / "x => src").mkdir()
    (repo / "x => src" / "main.py").write_text("1\n2\n", encoding="utf-8")
    _commit(repo, "arrow")

    reader = GitReader(repo)
    reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])

    assert "x => src/main.py" in {stats.path for stats in reader.file_stats}


# Below: a value Git ends at a line feed alone, or keeps whole, that `splitlines` or `strip`
# cut. LS, U+2028, is one character `splitlines` ends a line at and `strip` removes.
LS = "\u2028"
_KEEPS_TRAILING_SPACE = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows drops a trailing space from a file name"
)
_POSIX_PIPES = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX")


def _summary(repo: Path) -> Any:
    return CliRunner().invoke(app, ["summary", "--repo", str(repo)])


@pytest.mark.parametrize(("value", "partial"), [("false", False), ("true", True)])
@pytest.mark.parametrize("scope", ["local", "global"])
def test_a_promisor_on_a_remote_whose_name_holds_a_space(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    value: str,
    partial: bool,
) -> None:
    """Global config is read only through `git config`, not with `.git/config`."""
    if scope == "global":
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global"))
    _git(repo, "config", f"--{scope}", "remote.x y.promisor", value)

    result = _summary(repo)

    if partial:
        assert result.exit_code == ExitCode.CANNOT_RUN and "partial clone" in result.stderr
    else:
        assert result.exit_code == ExitCode.SUCCESS, result.stderr


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("r ", id="space", marks=_KEEPS_TRAILING_SPACE),
        pytest.param(f"r{LS}", id="line-separator"),
    ],
)
def test_a_repository_whose_directory_name_ends_in_a_space_is_read(
    tmp_path: Path, name: str
) -> None:
    """`--show-toplevel` is that directory; it does not set its working tree elsewhere."""
    path = tmp_path / name
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1\n", encoding="utf-8")
    _commit(path, "base")

    result = _summary(path)

    assert result.exit_code == ExitCode.SUCCESS, result.stderr


def test_the_object_directories_are_those_git_reads(tmp_path: Path) -> None:
    """One alternate per line feed, the path as written: lines Git 2.56 reads so."""
    objects, found, plain = tmp_path / "objects", tmp_path / f"a{LS}b", tmp_path / "plain"
    for directory in (objects, found, plain):
        (directory / "info").mkdir(parents=True)
    # Windows drops a trailing space from a file name, so `plain ` there names `plain`.
    trailing = "" if sys.platform == "win32" else f"{plain} \n"
    (objects / "info" / "alternates").write_bytes(
        f"{found}\n {plain}\n{trailing}{plain}\r\n# {plain}\n\n".encode()
    )

    assert _object_directories(objects) == [objects, found]


@_POSIX_PIPES
def test_a_pipe_in_an_alternate_whose_path_holds_a_line_separator(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_reader, "GIT_TIMEOUT_SECONDS", 3)
    shared = tmp_path / f"shared{LS}objects"
    (shared / "info").mkdir(parents=True)
    (repo / ".git" / "objects" / "info" / "alternates").write_text(f"{shared}\n", encoding="utf-8")
    os.mkfifo(shared / "info" / "alternates")

    result = _summary(repo)

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "not a regular file" in result.stderr, result.stderr


@_POSIX_PIPES
def test_a_worktree_of_a_repository_whose_path_holds_a_line_separator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common directory's `info/attributes` is found though its path holds U+2028."""
    monkeypatch.setattr(git_reader, "GIT_TIMEOUT_SECONDS", 3)
    main = tmp_path / f"m{LS}n"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "a").write_text("1\n", encoding="utf-8")
    _commit(main, "base")
    _git(main, "worktree", "add", "-q", str(tmp_path / "wt"))
    (main / ".git" / "info").mkdir(exist_ok=True)
    os.mkfifo(main / ".git" / "info" / "attributes")

    code, _ = _json(tmp_path / "wt")
    result = CliRunner().invoke(app, ["generate", "--repo", str(tmp_path / "wt"), "-o", "-"])

    assert code == ExitCode.CANNOT_RUN
    assert "info/attributes" in result.stderr and "not a regular file" in result.stderr


@_POSIX_PIPES
def test_an_attributes_file_whose_name_ends_in_a_quoted_space(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_reader, "GIT_TIMEOUT_SECONDS", 3)
    os.mkfifo(repo / "attrs ")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as config:
        config.write('[core]\n\tattributesFile = "attrs "\n')

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "-o", "-"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "attrs " in result.stderr and "not a regular file" in result.stderr, result.stderr


@_POSIX_PIPES
def test_a_git_file_pointing_to_a_directory_whose_name_ends_in_a_space(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git keeps the trailing space of a `gitdir:` path; `real ` is not `real`."""
    monkeypatch.setattr(git_reader, "GIT_TIMEOUT_SECONDS", 3)
    real = tmp_path / "real "
    (repo / ".git").rename(real)
    (repo / ".git").write_text(f"gitdir: {real}\n", encoding="utf-8")
    (real / "config").rename(real / "config.moved")
    os.mkfifo(real / "config")

    result = _summary(repo)

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "real /config" in result.stderr and "not a regular file" in result.stderr


@_POSIX_PIPES
def test_a_commondir_whose_path_ends_in_a_space(tmp_path: Path) -> None:
    common = tmp_path / "start" / ".git" / "common "
    common.mkdir(parents=True)
    (common.parent / "commondir").write_text("common \n", encoding="utf-8")
    os.mkfifo(common / "config")

    with pytest.raises(RepositoryError, match="common /config"):
        _refuse_git_files_that_block(tmp_path / "start", search_up=False)


@_POSIX_PIPES
def test_a_git_file_git_rejects_names_no_directory(tmp_path: Path) -> None:
    """Git needs "gitdir: " with its space; "gitdir:PATH" is not a Git file."""
    target = tmp_path / "target"
    target.mkdir()
    os.mkfifo(target / "config")
    (tmp_path / "start").mkdir()
    (tmp_path / "start" / ".git").write_text(f"gitdir:{target}\n", encoding="utf-8")

    _refuse_git_files_that_block(tmp_path / "start", search_up=False)


def test_history_not_followed_finds_grafts_in_a_common_directory_ending_in_ls(
    repo: Path, tmp_path: Path
) -> None:
    bare = tmp_path / f"b{LS}"
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    _git(bare, "worktree", "add", "-q", str(tmp_path / "wt"))
    (bare / "info").mkdir(exist_ok=True)
    (bare / "info" / "grafts").write_text("", encoding="utf-8")

    assert GitReader(tmp_path / "wt").history_not_followed() == (0, True)


def test_a_replace_ref_whose_name_holds_a_line_separator_counts_once(repo: Path) -> None:
    _git(repo, "update-ref", f"refs/replace/a{LS}b", _git(repo, "rev-parse", "HEAD").strip())

    assert GitReader(repo).history_not_followed() == (1, False)


def test_an_address_that_only_looks_no_reply_once_stripped(repo: Path) -> None:
    """The newest address ends in U+2028, so it is not account 7's; Ana keeps hers."""
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a", email="7+ana@users.noreply.github.com")
    _git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "e",
        name="Eve",
        email=f"7+eve@users.noreply.github.com{LS}",
    )

    code, report = _json(repo, "--no-ranking")

    assert code == ExitCode.SUCCESS
    emails = {c["email"] for c in report["contributors"] if c["name"] == "Ana"}
    assert "7+ana@users.noreply.github.com" in emails, report["contributors"]


@_KEEPS_TRAILING_SPACE
def test_the_root_of_a_worktree_whose_name_ends_in_a_space(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt "
    _git(repo, "worktree", "add", "-q", "-b", "w", str(worktree))
    (worktree / "sub").mkdir()

    assert repository_root(worktree / "sub") == worktree.resolve()
