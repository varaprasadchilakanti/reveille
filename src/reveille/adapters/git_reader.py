# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Git repository reader adapter: the only module that imports GitPython.

Contributors are keyed on author email, named from their most recent commit.
`.mailmap` is applied first, then GitHub's two noreply forms are folded together.
Merge commits are excluded from all analysis.

History is read in one `git log --numstat` subprocess; `Commit.stats` would
spawn one `git diff` per commit.
"""

from __future__ import annotations

import contextlib
import datetime
import functools
import logging
import os
import re
import secrets
import shlex
import stat
import sys
import tempfile
import threading
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, NoReturn

from git import Git, InvalidGitRepositoryError, NoSuchPathError, Repo
from git.compat import safe_decode
from git.exc import GitCommandError

from reveille.domain.areas import ROOT_AREA, area_of
from reveille.domain.files import is_generated
from reveille.domain.models import (
    AreaActivity,
    Commit,
    ContributorStats,
    FileStats,
    RepositoryMetadata,
)
from reveille.domain.repositories import MAX_SEARCH_DEPTH
from reveille.domain.state import RepositoryState, Worktree, quiet_branches
from reveille.exceptions import EmptyRepositoryError, RepositoryError

# Separators for the `git log` read: 0x1E and 0x1F are rare, not impossible.
# Git does not strip them from author fields, so a crafted commit can split a
# record; every field is scrubbed after parsing (_strip_control_chars).
_logger = logging.getLogger(__name__)

_RECORD_SEP = "\x1e"
_RECORD_SEP_BYTES = _RECORD_SEP.encode()
_FIELD_SEP = "\x1f"

# The hash closes the record as well as opening it: a commit cannot carry its
# own hash in its own author name, so an injected record never frames itself.
_LOG_FORMAT = f"--format={_RECORD_SEP}%H{_FIELD_SEP}%an{_FIELD_SEP}%ae{_FIELD_SEP}%ct{_FIELD_SEP}%H"

# A well-formed record opens with a 40-character object name.
_SHA_RE = re.compile(r"[0-9a-f]{40}")

#: Environment variables that make Git read a repository other than the one named.
_REPOSITORY_VARIABLES = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"}
)

#: The oldest Git every read works with: `--end-of-options` arrived in 2.24.
_MIN_GIT = (2, 24)

# C0 controls and DEL, tab and newlines included: they break downstream formats.
# C0, DEL and C1: some terminals obey a C1 control (U+009B is CSI) given as UTF-8.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# A byte that is not UTF-8 decodes to a lone surrogate, which no output can encode.
_UNDECODED_RE = re.compile(r"[\ud800-\udfff]")

# Bidi overrides, embeddings and isolates, zero-width space and BOM: they change
# how a name displays. ZWJ, ZWNJ, LRM and RLM are kept; real names use them.
_INVISIBLE_IN_NAMES_RE = re.compile("[\u202a-\u202e\u2066-\u2069\u200b\ufeff]")

# Caps on attacker-controlled identity fields, which the report repeats many
# times. 320 is the RFC 5321 address maximum; truncation is visibly marked.
_MAX_NAME_LENGTH = 256
_MAX_EMAIL_LENGTH = 320
_TRUNCATION_MARKER = "\u2026"
# Exclusions match on more than is shown, but not on everything: both sides are
# cut alike, so two names sharing this much are one name to an exclusion.
_MAX_MATCH_LENGTH = 4096

# GitHub's noreply addresses: `ID+username@` (an account number never reused) and the
# legacy `username@` (a name that can change hands). ADR 0023 folds on the number.
_GITHUB_NOREPLY_RE = re.compile(
    r"^(?P<account>\d+)\+(?P<username>[^@]+)@users\.noreply\.github\.com$",
    re.IGNORECASE,
)
_GITHUB_LEGACY_NOREPLY_RE = re.compile(
    r"^(?P<username>[^@+]+)@users\.noreply\.github\.com$",
    re.IGNORECASE,
)


def _name_and_email(text: str, *, allow_empty: bool) -> tuple[str | None, str, str] | None:
    """Read `name <email>` from the start of `text`, as Git's `parse_name_and_email` does.

    The address runs from the first `<` to the next `>`; the name is what comes
    before, trimmed, or None if empty.

    Args:
        text: What is left of the line.
        allow_empty: Whether `<>` is accepted (Git allows it for the commit address).

    Returns:
        The name, the address and the text after it, or None if there is no address.
    """
    left = text.find("<")
    right = text.find(">", left + 1) if left >= 0 else -1
    if right < 0 or (right == left + 1 and not allow_empty):
        return None
    name = text[:left].strip(" \t\r\n\v\f")
    return (name or None), text[left + 1 : right], text[right + 1 :]


def _parse_mailmap_line(line: str) -> tuple[str | None, str | None, str | None, str] | None:
    """Parse one `.mailmap` line as Git's `read_mailmap_line` does.

    A line starting with `#` is a comment. The first `<...>` is the proper
    address (with any name before it), an optional second one is the commit
    address (with any name before it), and anything after is ignored. A single
    address names both: the proper name applies to that address. Linear: no
    pattern can backtrack on a hostile line.

    Args:
        line: One line of the file, without its newline.

    Returns:
        `(proper_name, proper_email, commit_name, commit_email)`; a None proper
        field keeps the commit's own. None when the line maps nothing.
    """
    if line.startswith("#"):
        return None
    first = _name_and_email(line, allow_empty=False)
    if first is None:
        return None
    name, email, rest = first
    second = _name_and_email(rest, allow_empty=True) if rest else None
    if second is None:
        return (name, None, None, email)
    commit_name, commit_email, _ = second
    return (name, email, commit_name, commit_email)


def _normalise_github_noreply(email: str, mailmap: _Mailmap) -> str:
    """Fold a GitHub noreply address onto its account (ADR 0023).

    A prefixed address folds on its account number, so a renamed account stays
    one person; a legacy address joins an account only when its username
    belongs to exactly one account in the history read, else it stays apart.

    Args:
        email: An author email address, in any form.
        mailmap: Carries the account table built by `GitReader._noreply_accounts`.

    Returns:
        The account's canonical address, or the address unchanged.
    """
    prefixed = _GITHUB_NOREPLY_RE.match(email)
    if prefixed is not None:
        return mailmap.noreply_accounts.get(prefixed.group("account"), email)
    legacy = _GITHUB_LEGACY_NOREPLY_RE.match(email)
    if legacy is not None:
        return mailmap.noreply_usernames.get(legacy.group("username").lower(), email)
    return email


@dataclass(frozen=True)
class _Mailmap:
    """Parsed `.mailmap` lookup tables, most specific form kept apart.

    Attributes:
        by_email: Keyed on lowercased commit email; a `None` name keeps the commit's own.
        by_name_and_email: Keyed on lowercased (name, email); the four-field form.
    """

    by_email: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    by_name_and_email: dict[tuple[str, str], tuple[str | None, str]] = field(default_factory=dict)
    #: Account number to its canonical noreply address (ADR 0023).
    noreply_accounts: dict[str, str] = field(default_factory=dict)
    #: Lowercased legacy username to that address, only when one account used it.
    noreply_usernames: dict[str, str] = field(default_factory=dict)

    def lookup(self, name: str, email: str) -> tuple[str | None, str] | None:
        """Find the most specific entry matching a commit identity, case-insensitively.

        Args:
            name: Author name as recorded on the commit.
            email: Author email as recorded on the commit.

        Returns:
            The (canonical_name, canonical_email) entry, or None.
        """
        entry = self.by_name_and_email.get((name.lower(), email.lower()))
        if entry is not None:
            return entry
        return self.by_email.get(email.lower())


def _resolve_identity(name: str, email: str, mailmap: _Mailmap) -> tuple[str, str]:
    """Resolve a raw author identity to its canonical name and email.

    A `.mailmap` entry always wins, matched on the raw then the normalised
    noreply address; otherwise noreply normalisation applies.

    Args:
        name: Author name as recorded on the commit.
        email: Author email as recorded on the commit.
        mailmap: Parsed mappings from `_read_mailmap`.

    Returns:
        A tuple of (canonical_name, canonical_email).
    """
    normalised = _normalise_github_noreply(email, mailmap)

    mapped = mailmap.lookup(name, email)
    if mapped is None and normalised != email:
        mapped = mailmap.lookup(name, normalised)
    prefixed = _GITHUB_NOREPLY_RE.match(email)
    if mapped is None and prefixed is not None:
        # An entry written against the legacy form still catches the prefixed one.
        mapped = mailmap.lookup(name, f"{prefixed.group('username')}@users.noreply.github.com")

    if mapped is not None:
        canonical_name, canonical_email = mapped
        # The email-only form replaces the address but keeps the name.
        return (name if canonical_name is None else canonical_name), canonical_email

    return name, normalised


def _sum_numstat(block: str) -> tuple[int, int]:
    """Total the insertions and deletions in a `git log --numstat` block.

    Args:
        block: One commit's numstat lines; may be empty.

    Returns:
        A tuple of (lines_added, lines_deleted).
    """
    added = 0
    deleted = 0
    # The lines `_iter_numstat` reads, without decoding a path only to drop it.
    for line in block.splitlines():
        fields = line.split("\t", 2)
        if len(fields) < 3:
            continue
        added += int(fields[0]) if fields[0].isdigit() else 0
        deleted += int(fields[1]) if fields[1].isdigit() else 0
    return added, deleted


def _iter_numstat(block: str) -> Iterator[tuple[str, int, int]]:
    """Yield `(path, added, deleted)` for each file in one numstat block.

    A rename yields its destination; a binary file (`-` counts) counts zero.

    Args:
        block: One commit's numstat lines; may be empty.

    Yields:
        One `(path, added, deleted)` triple per file.
    """
    for line in block.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        raw_added, raw_deleted, path = fields[0], fields[1], fields[2]
        added = int(raw_added) if raw_added.isdigit() else 0
        deleted = int(raw_deleted) if raw_deleted.isdigit() else 0
        yield _numstat_path(path), added, deleted


def _directory_prefixes(path: str) -> set[str]:
    """Return `path` and each prefix of it that ends before a `/`.

    Args:
        path: A repository path, `/`-separated.

    Returns:
        For `a/b/c.py`: `a`, `a/b` and `a/b/c.py`.
    """
    prefixes = {path}
    end = path.find("/")
    while end != -1:
        prefixes.add(path[:end])
        end = path.find("/", end + 1)
    return prefixes


def _iter_name_status(block: str) -> Iterator[tuple[str, str]]:
    """Yield `(status, path)` for each file in one `--name-status` block.

    A rename or copy yields its destination with status "R" or "C".

    Args:
        block: One commit's name-status lines; may be empty.

    Yields:
        One `(status letter, path)` pair per file.
    """
    for line in block.splitlines():
        fields = line.split("\t")
        if len(fields) < 2 or not fields[0]:
            continue
        yield fields[0][0], _unquote_path(fields[-1])


def _record_files(record: str, name_status: bool) -> tuple[list[tuple[str, int, int]], list[str]]:
    """Return one record's files as `(path, added, deleted)`, and the paths it added.

    Args:
        record: One `git log` record, header line then the file block.
        name_status: Whether the block is `--name-status` rather than `--numstat`.

    Returns:
        The files (line counts zero under name-status) and the added paths.
    """
    _, _, block = record.partition("\n")
    if not name_status:
        return list(_iter_numstat(block)), []
    files: list[tuple[str, int, int]] = []
    added: list[str] = []
    for status, path in _iter_name_status(block):
        files.append((path, 0, 0))
        if status == "A":
            added.append(path)
    return files, added


@dataclass
class _Status:
    """The parsed `git status --porcelain=v2 --branch -z` output."""

    head: str | None = None
    branch: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    conflicted: list[str] = field(default_factory=list)
    staged: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)


def _parse_status(output: str) -> _Status:
    """Parse `git status --porcelain=v2 --branch -z`: NUL-separated, paths unquoted.

    Args:
        output: Git's output.

    Returns:
        Branch headers and paths by category; a path may be in more than one.
    """
    status = _Status()
    fields = iter(output.split("\0"))
    for entry in fields:
        if entry.startswith("# "):
            _status_header(entry, status)
        elif entry.startswith("? "):
            status.untracked.append(entry[2:])
        elif entry.startswith("u "):
            status.conflicted.append(entry.split(" ", 10)[-1])
        elif entry.startswith(("1 ", "2 ")):
            _status_change(entry, status)
            if entry.startswith("2 "):
                next(fields, None)  # a rename's original path
    return status


def _status_header(entry: str, status: _Status) -> None:
    """Fold one `# branch.*` header into `status`."""
    key, _, value = entry.removeprefix("# ").partition(" ")
    if key == "branch.oid":
        status.head = None if value == "(initial)" else value
    elif key == "branch.head":
        status.branch = None if value == "(detached)" else value
    elif key == "branch.upstream":
        status.upstream = value
    elif key == "branch.ab":
        ahead, _, behind = value.partition(" ")
        status.ahead, status.behind = int(ahead.lstrip("+")), int(behind.lstrip("-"))


def _status_change(entry: str, status: _Status) -> None:
    """Fold one ordinary (`1`) or renamed (`2`) entry into `status`."""
    parts = entry.split(" ", 9 if entry.startswith("2 ") else 8)
    path, xy = parts[-1], parts[1]
    if entry.startswith("2 "):
        status.renamed.append(path)
    if xy[0] != ".":
        status.staged.append(path)
    if xy[1] in "MT":
        status.modified.append(path)
    if "D" in xy:
        status.deleted.append(path)


def _parse_worktrees(output: str, *, nul: bool = True) -> list[Worktree]:
    """Parse `git worktree list --porcelain`, NUL-terminated (`-z`) or not.

    With `-z` each field ends in NUL and a record in an empty field, so a path
    holding a newline is read whole; without it, records are blank-line separated.

    Args:
        output: Git's output.
        nul: Whether it was produced with `-z`.

    Returns:
        The worktrees, the main one first.
    """
    found: list[Worktree] = []
    records = output.strip("\0").split("\0\0") if nul else output.strip().split("\n\n")
    for record in records:
        values: dict[str, str] = {}
        for line in record.split("\0") if nul else record.splitlines():
            key, _, value = line.partition(" ")
            values[key] = value
        if "worktree" not in values:
            continue
        branch = values.get("branch", "").removeprefix("refs/heads/") or None
        found.append(
            Worktree(
                path=values["worktree"],
                branch=branch,
                locked="locked" in values,
                prunable="prunable" in values,
            )
        )
    return found


def _same_directory(recorded: str, directory: Path) -> bool:
    """Return whether the path Git recorded is `directory`; False if it is gone."""
    try:
        return os.path.samefile(recorded, directory)
    except (OSError, ValueError):
        return False


def _numstat_path(field: str) -> str:
    """Return the path a numstat field names, decoded and after any rename.

    Git quotes each side of a plain rename separately, so its destination is
    taken before decoding; anything else is decoded whole first.

    Args:
        field: One numstat path field.

    Returns:
        The file's path as it is now.
    """
    if " => " in field and "{" not in field:
        return _unquote_path(field.rsplit(" => ", 1)[1].strip())
    return _rename_destination(_unquote_path(field))


#: C escapes Git uses in a quoted path, other than octal byte escapes.
_PATH_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote_path(path: str) -> str:
    r"""Decode a path Git printed in quoted form (`"src/na\303\257ve.py"`).

    Left quoted, a non-ASCII path would show as a separate hotspot and area.

    Args:
        path: One numstat path field.

    Returns:
        The path as UTF-8 text, or the input unchanged when it is not quoted.
    """
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\" or index + 1 == len(body):
            out.extend(char.encode("utf-8"))
            index += 1
            continue
        following = body[index + 1]
        octal = body[index + 1 : index + 4]
        if len(octal) == 3 and all(c in "01234567" for c in octal):
            out.append(int(octal, 8) & 0xFF)
            index += 4
        elif following in _PATH_ESCAPES:
            out.append(_PATH_ESCAPES[following])
            index += 2
        else:
            out.extend(char.encode("utf-8"))
            index += 1
    return out.decode("utf-8", errors="replace")


def _rename_destination(path: str) -> str:
    """Return the path a file has after a rename, or the path unchanged.

    Handles `dir/{old => new}/f.py` and bare `old => new`; the source no longer exists.

    Args:
        path: One numstat path field.

    Returns:
        The destination path, with any rename notation resolved.
    """
    if "=>" not in path:
        return path
    if "{" in path and "}" in path:
        prefix, _, rest = path.partition("{")
        inner, _, suffix = rest.partition("}")
        _, _, destination = inner.partition("=>")
        return f"{prefix}{destination.strip()}{suffix}".replace("//", "/")
    _, _, destination = path.partition("=>")
    return destination.strip()


@dataclass
class _AreaTotal:
    """Running totals for one area while the log streams."""

    commits: int
    last_changed: datetime.date
    authors: dict[str, datetime.date] = field(default_factory=dict)
    first_changed: datetime.date | None = None


def _accumulate_area_totals(
    files: list[tuple[str, int, int]],
    commit: Commit,
    depth: int | None,
    totals: dict[str, _AreaTotal],
) -> None:
    """Fold one commit into the per-area totals: once per area it touched.

    Memory is bounded by areas times authors; generated lock files are skipped.

    Args:
        files: The commit's files, as `_record_files` returns them.
        commit: The parsed commit, for its author and date.
        depth: Most directory components per area, or None to keep nothing.
        totals: Mutated in place, keyed by area.
    """
    if depth is None:
        return
    areas = {area_of(path, depth) for path, _, _ in files if not is_generated(path)}
    day = commit.timestamp.date()
    author = commit.author_email.lower()
    for area in areas:
        total = totals.get(area)
        if total is None:
            totals[area] = _AreaTotal(
                commits=1, last_changed=day, authors={author: day}, first_changed=day
            )
        else:
            total.commits += 1
            total.last_changed = max(total.last_changed, day)
            total.first_changed = min(total.first_changed or day, day)
            total.authors[author] = max(total.authors.get(author, day), day)


def _accumulate_file_totals(
    files: list[tuple[str, int, int]], totals: dict[str, list[int]]
) -> None:
    """Fold one commit's files into the running per-path totals.

    Args:
        files: The commit's files, as `_record_files` returns them.
        totals: Mutated in place: path to `[commits, lines_added, lines_deleted]`.
    """
    for path, added, deleted in files:
        entry = totals.get(path)
        if entry is None:
            totals[path] = [1, added, deleted]
        else:
            entry[0] += 1
            entry[1] += added
            entry[2] += deleted


def _without_credentials(url: str) -> str:
    """Remove a password or token from a remote URL, which the report prints.

    HTTP(S) drops the whole user part (a token may be the user name); other
    schemes keep the login. Query and fragment go; a `helper::` prefix is kept,
    the scheme after it decides. Not `urlsplit`: it raises on URLs Git accepts.

    Args:
        url: The remote URL as Git stores it.

    Returns:
        The URL without a password, token, query string or fragment.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        # scp-like `user@host:path`; a `user:secret@` written there keeps only its
        # login. The user part ends at the last `@` followed by `host:`, so an `@`
        # in the secret or in the path is not taken for the end of it.
        cut = len(url)
        while (cut := url.rfind("@", 0, cut)) != -1:
            host, colon, _ = url[cut + 1 :].partition(":")
            if colon and host and not any(c in host for c in "@/\\"):
                break
        else:
            return url
        userinfo = url[:cut]
        if ":" in userinfo and not any(c in userinfo for c in "/\\"):
            return f"{userinfo.partition(':')[0]}{url[cut:]}"
        return url
    authority, slash, path = rest.partition("/")
    # The user part ends at the last `@` before the path, so a raw `#` or `?`
    # inside a password is stripped with it; query and fragment go after.
    userinfo, at, host = authority.rpartition("@")
    host = host.split("#", 1)[0].split("?", 1)[0]
    path = path.split("#", 1)[0].split("?", 1)[0]
    authority = f"{userinfo}{at}{host}"
    if at:
        if scheme.rpartition("::")[2].lower() in ("http", "https"):
            authority = host
        else:
            authority = f"{userinfo.partition(':')[0]}@{host}"
    return f"{scheme}://{authority}{slash}{path}"


def _exclusion_unreadable(rev: str, exc: GitCommandError) -> RepositoryError:
    """Build the error for history an exclusion needs but Git would not give.

    Args:
        rev: The analysed revision.
        exc: Git's failure.

    Returns:
        The error to raise.
    """
    return RepositoryError(
        f"Failed to read the history on '{rev}' that --exclude-author is checked against, "
        "so the exclusion cannot be applied in full. "
        f"Detail: {exc}"
    )


class GitReader:
    """Reads commit history and metadata from a local Git repository.

    Args:
        repo_path: Path to the repository root. Must contain a .git directory.

    Raises:
        RepositoryError: If the path is missing, unreadable or not a repository.
    """

    def __init__(self, repo_path: Path) -> None:
        """Initialise the reader and validate the repository path.

        Args:
            repo_path: Path to the Git repository root.

        Raises:
            RepositoryError: If the path is not a valid readable Git repository.
        """
        self._mailmap_applied = False
        self._active_branch: str | None = None
        self._branch_refs: dict[str, str] = {}
        self._file_stats: tuple[FileStats, ...] = ()
        #: Commits the last `read_commits` dropped as dated after `dated_until`.
        self.commits_dated_after: int = 0
        #: Commits whose log record could not be read; counted nowhere, stated (ADR 0019).
        self.commits_unreadable: int = 0
        #: Merge commits in the last `read_commits` selection, left out of every figure.
        self.merges_excluded: int = 0
        #: Who changed each directory, when `read_commits` got an `area_depth`.
        self.area_activity: tuple[AreaActivity, ...] = ()
        #: Files added in the last `read_commits` with `name_status`.
        self.files_added: int = 0
        self.unmatched_exclusions: tuple[str, ...] = ()
        #: The `--exclude-author` values, as given, that matched something.
        self.matched_exclusions: tuple[str, ...] = ()
        self.unmatched_path_exclusions: tuple[str, ...] = ()
        _refuse_git_files_that_block(repo_path, search_up=False)
        try:
            self._repo = _TimedRepo(str(repo_path), search_parent_directories=False)
        except InvalidGitRepositoryError as exc:
            # An unreadable `.git` raises the same exception as a missing one;
            # the fixes differ, so tell them apart.
            git_dir = repo_path / ".git"
            named = _git_dir_of(repo_path, search_up=False) if git_dir.is_file() else None
            if named is not None and not named.exists():
                raise RepositoryError(
                    f"'{repo_path}' has a .git file naming '{named}', which does not exist: "
                    "the repository it belongs to was moved or deleted. If it was moved, run "
                    f"`git worktree repair {shlex.quote(str(repo_path))}` in its new place."
                ) from exc
            if git_dir.is_dir() and not os.access(git_dir, os.R_OK | os.X_OK):
                raise RepositoryError(
                    f"'{repo_path}' is a Git repository, but its .git directory "
                    "cannot be read. Check the permissions on it."
                ) from exc
            raise RepositoryError(
                f"'{repo_path}' is not a valid Git repository. "
                "Give a directory inside a working tree, or a bare repository."
            ) from exc
        except NoSuchPathError as exc:
            raise RepositoryError(f"'{repo_path}' does not exist.") from exc
        self._repo_path = repo_path.resolve()
        # A partial clone fetches missing objects on read: a network call and a
        # Git data change. GIT_NO_LAZY_FETCH needs Git 2.44, so it is refused.
        # Replace refs and grafts are ignored too (ADR 0018). No optional locks: a
        # plain `git status` rewrites the index (ADR 0024).
        self._repo.git.update_environment(
            GIT_NO_LAZY_FETCH="1",
            GIT_NO_REPLACE_OBJECTS="1",
            GIT_GRAFT_FILE=os.devnull,
            GIT_OPTIONAL_LOCKS="0",
            # To a pipe, Git flushes after every record unless GIT_FLUSH=0: a write, and a
            # wake-up of the reader, per commit. At 0 it writes in blocks.
            GIT_FLUSH="0",
        )
        version = self._git_version()
        if version is not None and version < _MIN_GIT:
            raise RepositoryError(
                f"Reveille needs Git {_MIN_GIT[0]}.{_MIN_GIT[1]} or newer, which every read "
                f"relies on (--end-of-options); this is Git {version[0]}.{version[1]}."
            )
        # GitPython cannot parse SHA-256 refs and reads HEAD as unborn: refuse
        # rather than answer "no commits". Git before 2.29 echoes the option. One
        # call: the Git directory's line only shows Git could open the repository.
        try:
            opened = str(self._git().rev_parse("--git-dir", "--show-object-format"))
        except GitCommandError as exc:
            _refuse_what_git_cannot_open(repo_path, exc)
        if opened.strip().splitlines()[-1:] == ["sha256"]:
            raise RepositoryError(
                f"'{repo_path}' uses SHA-256 object names, which Reveille cannot read yet."
            )
        self._refuse_a_working_tree_elsewhere(repo_path)
        self._pin_locations()
        if _is_partial_clone(self._repo) or self._promisor_in_any_scope():
            raise RepositoryError(
                f"'{repo_path}' is a partial clone (made with --filter): some of its "
                "objects are still on the server, and reading them would make Git "
                "fetch them. Reveille makes no network call and changes no Git data, "
                "so it does not read a partial clone. Run it on a full clone."
            )

    def _refuse_attribute_files_that_block(self, *, counts_lines: bool) -> None:
        """Refuse when a file Git reads attributes from is not a regular file.

        Counting lines (`--numstat`) makes Git read attributes, to tell binary files
        apart: `.gitattributes` in the working tree, `info/attributes`, and
        `core.attributesFile`. A named pipe there blocks the read for ever, and a
        device can feed it without end. A copied directory or an archive can carry
        one; `git clone` cannot. Every directory of the working tree is checked,
        tracked or not, apart from `.git`; symbolic links are not followed.

        Args:
            counts_lines: Whether the read counts lines; only then are attributes read.

        Raises:
            RepositoryError: If one is a named pipe, a device or a socket.
        """
        if not counts_lines:
            return
        candidates = self._attribute_files()
        for candidate in candidates:
            try:
                mode = candidate.stat().st_mode
            except OSError:
                continue
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RepositoryError(
                    f"'{candidate}' is not a regular file (a named pipe or a device). Git "
                    "reads attributes from it to count lines, and would wait on it for ever. "
                    "Remove it, or read without line counts (`reveille summary`)."
                )

    def _attribute_files(self) -> list[Path]:
        """Return the files Git may read attributes from when it counts lines.

        Returns:
            `info/attributes` in the Git and common directories, `core.attributesFile`,
            and `.gitattributes` in every directory of the working tree.
        """
        candidates: list[Path] = []
        try:
            found = str(self._git().rev_parse("--git-dir", "--git-common-dir")).splitlines()
        except GitCommandError:
            found = []
        for line in found:
            git_dir = Path(line) if Path(line).is_absolute() else self._repo_path / line
            candidates.append(git_dir / "info" / "attributes")
        try:
            configured = str(self._git().config("--get", "core.attributesFile")).strip()
        except GitCommandError:
            configured = ""
        if configured:
            # Git runs where GitPython starts it, so a relative path is relative to that.
            candidates.append(self._repo_path / os.path.expanduser(configured))
        if not self._repo.bare:
            # Every directory on disk, not only HEAD's: a path in older history is
            # looked up where it was, and that directory may exist untracked.
            for directory, subdirectories, _ in os.walk(self._repo_path):
                subdirectories[:] = [d for d in subdirectories if d != ".git"]
                candidates.append(Path(directory) / ".gitattributes")
                # Git follows a link to a directory; the walk does not. One level is
                # checked, and the deadline on every read covers what lies deeper.
                candidates.extend(
                    Path(directory) / d / ".gitattributes"
                    for d in subdirectories
                    if os.path.islink(os.path.join(directory, d))
                )
        return candidates

    def _pin_locations(self) -> None:
        """Pin the index, the object directory and the working tree to the repository's own.

        A hook runs with GIT_WORK_TREE or GIT_INDEX_FILE set, and Git honours them
        over the repository's layout; GitPython pins GIT_DIR alone. Run after
        `core.worktree` is checked, which a pinned working tree overrides.
        """
        self._repo.git.update_environment(
            GIT_INDEX_FILE=os.path.join(self._repo.git_dir, "index"),
            GIT_OBJECT_DIRECTORY=os.path.join(self._repo.common_dir, "objects"),
        )
        if not self._repo.bare:
            self._repo.git.update_environment(GIT_WORK_TREE=str(self._repo_path))

    def _refuse_a_working_tree_elsewhere(self, repo_path: Path) -> None:
        """Refuse a repository whose configuration puts its working tree somewhere else.

        `core.worktree` in a repository's own `.git/config`, which an archive or a
        copied directory carries, can name another repository's directory. The
        report would then describe that one's files and be written into it, under
        the name of the repository given. A linked worktree and a submodule keep
        their working tree where they are, so they pass.

        Args:
            repo_path: The repository as given, for the message.

        Raises:
            RepositoryError: If Git puts the working tree elsewhere.
        """
        # Git's answer would follow a caller's GIT_WORK_TREE, as a hook sets it, so the
        # setting itself is read then.
        try:
            if "GIT_WORK_TREE" in os.environ:
                named = str(self._git().config("--get", "core.worktree")).strip()
                top = str(Path(self._repo.git_dir, named)) if named else ""
            else:
                top = str(self._git().rev_parse("--show-toplevel")).strip()
        except GitCommandError:
            return  # No such setting, or a bare repository: no working tree elsewhere.
        if top and Path(top).resolve() != self._repo_path:
            if Path(self._repo.git_dir).resolve() == self._repo_path:
                raise RepositoryError(
                    f"'{repo_path}' is the Git directory of the working tree '{top}'. "
                    "Give the working tree instead."
                )
            raise RepositoryError(
                f"'{repo_path}' sets its working tree to '{top}' (core.worktree in its "
                "Git configuration). Reveille reads only the repository it is given, and "
                "that setting would make the report describe, and be written into, another "
                "directory. Remove the setting, or run Reveille in the other repository."
            )

    def read_commits(
        self,
        branch: str | None,
        since: datetime.date | None,
        until: datetime.date | None,
        exclude_authors: list[str],
        dated_until: datetime.date | None = None,
        area_depth: int | None = None,
        line_counts: bool = True,
        path: str | None = None,
        from_commit: str | None = None,
        name_status: bool = False,
        exclude_paths: Sequence[str] = (),
        report_unmatched: bool = True,
        co_authors: bool = True,
    ) -> list[Commit]:
        """Read all non-merge commits in the analysis window, in one `git log`.

        Exclusions match name, resolved email and raw email, case-insensitively.
        `until` is inclusive.

        Args:
            branch: Branch to read; the active branch if None.
            since: Earliest date included; unbounded if None.
            until: Latest date included; unbounded if None.
            exclude_authors: Author names or addresses to exclude.
            dated_until: Drop commits dated (UTC) after this, before files are
                counted, and count them in `commits_dated_after`.
            area_depth: Record per-directory activity at this depth (ADR 0013).
            line_counts: Read line counts; False is faster and reports zero lines.
            path: Only commits that changed this literal repository path.
            from_commit: A full SHA from `resolve_commit`; read `<sha>..<branch>` only.
            name_status: Read files without line counts (`--name-status`), and
                count the files added in `files_added`; overrides `line_counts`.
            exclude_paths: Literal repository paths left out of every figure. A
                commit that changed only these is not read.
            report_unmatched: Log a warning for a value or path that matched
                nothing. A caller reading many repositories reports it once instead.
            co_authors: Read `Co-authored-by` trailers; False credits nobody and
                saves a second `git log`, for a caller that counts authors only.

        Returns:
            Commits sorted most recent first.

        Raises:
            RepositoryError: If the branch does not exist.
            EmptyRepositoryError: If no commits remain after filtering.
        """
        # Cleared at entry so a call that raises leaves no stale result.
        self.unmatched_exclusions = ()
        self.matched_exclusions = ()
        self.unmatched_path_exclusions = ()

        rev = self._walked_revision(branch)

        # The range end is the branch; exclusions still reach its whole history (ADR 0020).
        walk = f"{from_commit}..{rev}" if from_commit is not None else rev
        log_args, rev_list_args = _build_log_args(
            walk,
            since,
            until,
            self._supports_since_as_filter(),
            line_counts=line_counts and not name_status,
            path=path,
            name_status=name_status,
            exclude_paths=exclude_paths,
        )

        # An unborn HEAD is a negative answer, not a read failure; a named branch
        # is read even then, and a missing one fails below.
        if branch is None and not self._head_is_born():
            raise EmptyRepositoryError(
                f"Repository at '{self._repo_path}' contains no commits. "
                "There is nothing to read until the first commit is made."
            )

        self._refuse_attribute_files_that_block(counts_lines=line_counts and not name_status)
        _logger.debug("git log %s", " ".join(log_args))
        # Started first: Git writes both logs while the queries below run. The
        # co-author read covers the same selection (ADR 0014).
        stream = _LogStream(self._git().log(*log_args, as_process=True))
        trailers: _LogStream | None = None
        try:
            trailers = self._trailer_stream(log_args, co_authors)
            records, authentic_order, mailmap, requests, reached = self._read_alongside(
                stream, rev, rev_list_args, exclude_authors
            )
            co_author_records = self._trailer_records(trailers)
        finally:
            stream.close()
            if trailers is not None:
                trailers.close()
        # One string per hash, shared by every structure that names it, so each hash
        # is held once.
        canonical = {sha: sha for sha in authentic_order}
        authentic_shas = canonical.keys()
        co_author_records = _shared_trailer_records(co_author_records, canonical)
        exclude_set = set().union(*requests.values())

        trusted = _well_formed_shas(records, canonical)
        undatable: set[str] = set()
        # An identity is its address (ADR 0002): excluding one name drops every
        # commit under the addresses it reaches.
        exclude_set |= {address for addresses in reached.values() for address in addresses}
        _state_wide_exclusions(reached)

        commits: list[Commit] = []
        matched: set[str] = set()
        # One resolution per author, not per commit: the same strings are shared.
        identities: dict[tuple[str, str], tuple[str, str, set[str]]] = {}
        # Accumulated while streaming: memory is bounded by distinct paths.
        file_totals: dict[str, list[int]] = {}
        area_totals: dict[str, _AreaTotal] = {}
        added_paths: set[str] = set()
        dated_after = 0
        # Not freed one by one: at 100,000 commits that lowers the JSON peak but
        # raises the heap left once the HTML report is rendered.
        for raw in records:
            # Decoded one at a time: the read holds Git's bytes, not a copy as text.
            record = safe_decode(raw)
            commit = _parse_log_record(
                record, mailmap, exclude_set, trusted, matched, undatable, identities
            )
            if commit is None:
                continue
            if dated_until is not None and commit.timestamp.date() > dated_until:
                dated_after += 1
                continue
            commits.append(commit)
            # Only surviving commits: an excluded author's churn must not reappear.
            files, added = _record_files(record, name_status)
            _accumulate_file_totals(files, file_totals)
            _accumulate_area_totals(files, commit, area_depth, area_totals)
            added_paths.update(added)

        self._file_stats = tuple(
            FileStats(path=path, commits=n, lines_added=a, lines_deleted=d)
            for path, (n, a, d) in file_totals.items()
        )
        self.commits_dated_after = dated_after
        self.files_added = len(added_paths)
        self.commits_unreadable = _unreadable(trusted.keys(), authentic_shas, undatable)
        # Not needed past here: freed before the co-authors are credited.
        record_count = len(records)
        del records
        self.area_activity = tuple(
            AreaActivity(
                area=area,
                commits=total.commits,
                last_changed=total.last_changed,
                authors=dict(total.authors),
                first_changed=total.first_changed,
            )
            for area, total in area_totals.items()
        )

        commits = self._credit_co_authors(
            co_author_records, authentic_order, commits, mailmap, exclude_set, matched
        )

        # A filter that matched nothing is almost always a typo; say so. A value
        # matched when any form it expanded to did, and only values given are named.
        # Assigned unconditionally so a reused reader never reports stale values.
        found = matched | set(reached)
        unmatched = sorted(value for value, forms in requests.items() if not forms & found)
        self.unmatched_exclusions = tuple(unmatched)
        self.matched_exclusions = tuple(
            value for value in exclude_authors if _match_key(value) not in unmatched
        )
        if unmatched and report_unmatched:
            _logger.warning("--exclude-author matched no commits for: %s", ", ".join(unmatched))

        self.unmatched_path_exclusions = self._paths_never_changed(rev, exclude_paths)
        if self.unmatched_path_exclusions and report_unmatched:
            _logger.warning(
                "--exclude-path matched no file in the history of %s: %s",
                rev,
                ", ".join(self.unmatched_path_exclusions),
            )

        if not commits:
            narrowed = {
                "widening the date range": since is not None or until is not None,
                "removing an --exclude-author value": bool(exclude_authors),
                "removing an --exclude-path value": bool(exclude_paths),
            }
            raise _empty_window(dated_after, dated_until, [k for k, v in narrowed.items() if v])

        _logger.debug(
            "read %d commits from %s (%d git log records)", len(commits), rev, record_count
        )
        return sorted(commits, key=lambda c: c.timestamp, reverse=True)

    def aggregate_contributor_stats(
        self,
        commits: list[Commit],
        min_commits: int,
    ) -> list[ContributorStats]:
        """Aggregate commits per contributor, keyed on lowercased email.

        The display name is taken from the most recent commit.

        Args:
            commits: Commits returned by read_commits.
            min_commits: Drop contributors with fewer commits than this.

        Returns:
            ContributorStats sorted by commit count descending.
        """
        grouped: dict[str, list[Commit]] = defaultdict(list)
        co_authored: dict[str, int] = defaultdict(int)
        for commit in commits:
            grouped[commit.author_email.lower()].append(commit)
            for _, email in commit.co_authors:
                co_authored[email] += 1

        result: list[ContributorStats] = []
        for email, contributor_commits in grouped.items():
            if len(contributor_commits) < min_commits:
                continue

            sorted_by_time = sorted(contributor_commits, key=lambda c: c.timestamp)
            display_name = sorted_by_time[-1].author_name
            active_dates = {c.timestamp.date() for c in contributor_commits}

            result.append(
                ContributorStats(
                    name=display_name,
                    email=email,
                    commit_count=len(contributor_commits),
                    lines_added=sum(c.lines_added for c in contributor_commits),
                    lines_deleted=sum(c.lines_deleted for c in contributor_commits),
                    active_days=len(active_dates),
                    first_commit_date=sorted_by_time[0].timestamp.date(),
                    last_commit_date=sorted_by_time[-1].timestamp.date(),
                    co_authored_commits=co_authored.get(email, 0),
                )
            )

        return sorted(result, key=lambda s: s.commit_count, reverse=True)

    def read_metadata(
        self,
        total_commits: int,
        unique_contributors: int,
        analysis_since: datetime.date,
        analysis_until: datetime.date,
        branch: str | None = None,
    ) -> RepositoryMetadata:
        """Read repository-level metadata; the name is the root directory's.

        Args:
            total_commits: Total commit count within the analysis window.
            unique_contributors: Unique contributor count after filtering.
            analysis_since: Start of the analysis window.
            analysis_until: End of the analysis window.
            branch: The ref analysed; the active branch, as in `read_commits`, if None.

        Returns:
            A populated RepositoryMetadata instance.
        """
        remote_url = self._resolve_remote_url()

        return RepositoryMetadata(
            name=self._repo_path.name,
            remote_url=remote_url,
            analysed_branch=_shown(branch or self._resolve_active_branch()),
            total_commits=total_commits,
            unique_contributors=unique_contributors,
            analysis_since=analysis_since,
            analysis_until=analysis_until,
            generated_at=datetime.datetime.now(tz=datetime.UTC),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _walked_revision(self, branch: str | None) -> str:
        """Return the revision a read walks: the branch given, or the active one.

        Args:
            branch: As given, possibly from an untrusted reveille.toml.

        Returns:
            The revision.

        Raises:
            RepositoryError: If it begins with `-` (git would read an option), or
                is not one branch, tag or commit (a range would narrow the history
                while the report still says "branch").
        """
        rev = self.branch_revision(branch)
        if rev.startswith("-"):
            raise RepositoryError(
                f"Refusing to use {rev!r} as a revision: a value beginning with "
                "'-' is interpreted by git as a command-line option rather than "
                "a branch. If a ref really has this name, rename it."
            )
        if branch is not None:
            self.resolve_commit(rev)
        return rev

    def _head_is_born(self) -> bool:
        """Return whether HEAD names a commit, as Git sees it; False when it is unborn.

        Asked of Git, not GitPython: GitPython says no for a HEAD it cannot
        parse or whose commit it cannot read, which made a repository with
        history, or a damaged one, read as having none.

        Raises:
            RepositoryError: If HEAD exists but names no commit Git can read.
        """
        try:
            self._git().rev_parse("--quiet", "--verify", "--end-of-options", "HEAD^{commit}")
        except GitCommandError:
            pass
        else:
            return True
        try:
            self._git().rev_parse("--quiet", "--verify", "--end-of-options", "HEAD")
        except GitCommandError:
            return False  # no such ref: unborn
        raise RepositoryError(
            f"HEAD in '{self._repo_path}' names an object that is missing or is not a "
            "commit, so the repository is damaged. Run `git fsck` to see what is wrong."
        )

    def _resolve_active_branch(self) -> str:
        """Return the active branch name, as shown, or 'HEAD' when detached.

        Returns:
            The branch name, or 'HEAD'.
        """
        return self._active_revision().removeprefix("refs/heads/")

    def branch_revision(self, branch: str | None) -> str:
        """Return the revision a branch name is read as: the branch, when there is one.

        Git reads `refs/tags/<name>` before `refs/heads/<name>` (gitrevisions(7)),
        so a tag sharing a branch's name stood in for it. Git's advice for that case
        is to name the ref in full, which also leaves nothing to its lookup order.
        A name that is no branch is left for Git to read as a tag or commit.

        Args:
            branch: As given; the active branch if None.

        Returns:
            `refs/heads/<name>` when that branch exists, else the name as given.
        """
        if branch is None:
            return self._active_revision()
        if branch.startswith(("-", "refs/")) or branch == "HEAD":
            return branch  # refused later, already in full, or the checked-out commit
        if branch not in self._branch_refs:
            self._branch_refs[branch] = (
                f"refs/heads/{branch}" if self._ref_exists(f"refs/heads/{branch}") else branch
            )
            if self._branch_refs[branch] != branch and self._ref_exists(f"refs/tags/{branch}"):
                _logger.warning(
                    "%r names both a branch and a tag; the branch is read. "
                    "Give --branch refs/tags/%s to read the tag.",
                    branch,
                    branch,
                )
        return self._branch_refs[branch]

    def _ref_exists(self, ref: str) -> bool:
        """Return whether this exact ref exists; `show-ref --verify` reads no revision syntax."""
        try:
            self._git().show_ref("--verify", "--quiet", ref)
        except GitCommandError:
            return False
        return True

    def _active_revision(self) -> str:
        """Return the active branch's full ref, as read, or 'HEAD' when detached.

        Git's answer, asked once: GitPython splits HEAD at U+2028, U+2029 and
        U+0085, which a branch name may hold, and stops on one that is not UTF-8.
        The full ref, because Git reads a tag before a branch of the same name.

        Returns:
            The ref, such as `refs/heads/main`, or 'HEAD'.
        """
        if self._active_branch is None:
            try:
                ref = str(self._git().symbolic_ref("--quiet", "HEAD")).rstrip("\n")
            except GitCommandError:
                ref = "HEAD"
            self._active_branch = ref
        return self._active_branch

    def _read_alongside(
        self,
        stream: _LogStream,
        rev: str,
        rev_list_args: list[str],
        exclude_authors: list[str],
    ) -> tuple[list[bytes], list[str], _Mailmap, dict[str, set[str]], dict[str, set[str]]]:
        """Run the queries the main read needs while Git writes the log, then take it.

        Args:
            stream: The main `git log`, already started.
            rev: The analysed revision.
            rev_list_args: The `rev-list` arguments matching the log's selection.
            exclude_authors: The `--exclude-author` values.

        Returns:
            The log's records as Git wrote them, the authentic hashes in log order, the mailmap with
            the noreply accounts folded in, each exclusion's forms, and the
            addresses each exclusion reaches in the branch's history.

        Raises:
            RepositoryError: If the branch cannot be enumerated, the history an
                exclusion is checked against cannot be read, or the log not read.
        """
        # A crafted author name can inject a whole record, so authentic SHAs
        # come from `rev-list`, which computes them; a record whose SHA is not
        # in this set did not come from a commit.
        _logger.debug("git rev-list %s", " ".join(rev_list_args))
        try:
            # Ordered too: the co-author pass must line up one for one (ADR 0014).
            authentic_order = [
                line.strip()
                for line in str(self._git().rev_list(*rev_list_args)).splitlines()
                if line.strip()
            ]
            # The same selection's merges: left out of every figure (ADR 0001), and counted.
            merges = ["--merges" if a == "--no-merges" else a for a in rev_list_args]
            self.merges_excluded = int(str(self._git().rev_list("--count", *merges)).strip() or 0)
        except GitCommandError as exc:
            # The revision was resolved already, so the cause is elsewhere: say Git's.
            raise RepositoryError(
                f"Git could not list the commits on '{rev}': {_git_error(exc)}"
            ) from exc

        # Once the branch is known to exist: an exclusion names a person, through the mailmap.
        mailmap = self._read_mailmap()
        self._mailmap_applied = bool(mailmap.by_email or mailmap.by_name_and_email)
        accounts, usernames = self._noreply_accounts(rev)
        mailmap = replace(mailmap, noreply_accounts=accounts, noreply_usernames=usernames)
        requests = _exclusion_requests(exclude_authors, mailmap)
        reached = self._addresses_in_history(rev, mailmap, set().union(*requests.values()))

        try:
            records = stream.raw_records()
        except GitCommandError as exc:
            raise RepositoryError(
                f"Git could not read the commits on '{rev}': {_git_error(exc)}"
            ) from exc
        return records, authentic_order, mailmap, requests, reached

    def _credit_co_authors(
        self,
        co_author_records: list[str] | GitCommandError | None,
        authentic_order: list[str],
        commits: list[Commit],
        mailmap: _Mailmap,
        exclude_set: set[str],
        matched: set[str],
    ) -> list[Commit]:
        """Attach the identities each commit's `Co-authored-by` trailers credit.

        From a second NUL-separated `git log` over the same selection (ADR 0014).
        Records must line up one for one with `rev-list`, or a crafted trailer
        could forge another commit's record; otherwise nobody is credited.

        Args:
            co_author_records: That log's records, Git's failure to give them, or
                None when it was not read.
            authentic_order: Hashes from `rev-list`, in log order.
            commits: The commits being counted.
            mailmap: Parsed `.mailmap`, applied as for authors.
            exclude_set: Lowercased exclusions; a matching co-author is dropped.
            matched: Mutated with every exclusion value that matched.

        Returns:
            The commits, with `co_authors` set where any are credited.
        """
        if not commits or co_author_records is None:
            return commits
        if isinstance(co_author_records, GitCommandError):
            _logger.warning("co-author trailers could not be read: %s", co_author_records)
            return commits
        records = [r for r in co_author_records if r.strip()]
        hashes = [r.split(_FIELD_SEP, 1)[0].strip() for r in records]
        if hashes != authentic_order:
            _logger.warning(
                "co-author trailers did not line up with the commits read; "
                "no co-author is credited in this report"
            )
            return commits

        credited: dict[str, tuple[tuple[str, str], ...]] = {}
        authors = {c.sha: c.author_email.lower() for c in commits}
        crowded = ignored = 0
        for record in records:
            sha, _, values = record.partition(_FIELD_SEP)
            sha = sha.strip()
            if sha not in authors or not values.strip():
                continue
            found, dropped = _co_author_identities(
                values, mailmap, exclude_set, matched, authors[sha]
            )
            if found:
                credited[sha] = found
            if dropped:
                crowded, ignored = crowded + 1, ignored + dropped
        if crowded:  # once per read, not once per commit
            _logger.warning(
                "%d commit%s name more than %d co-authors; %d ignored",
                *(crowded, "" if crowded == 1 else "s", _MAX_CO_AUTHORS, ignored),
            )
        return [replace(c, co_authors=credited[c.sha]) if c.sha in credited else c for c in commits]

    def _promisor_in_any_scope(self) -> bool:
        """Ask Git whether any config it reads makes this a partial clone.

        GitPython's reader sees `.git/config` and its includes, but not
        worktree-scope config; before Git 2.44 nothing else stops a lazy fetch.
        Fails closed: if Git cannot answer, the repository is treated as partial.

        Returns:
            True for a promisor remote or `extensions.partialClone` in any scope.
        """
        try:
            out = str(
                self._git().config(
                    "--get-regexp", r"^(remote\..*\.promisor|extensions\.partialclone)$"
                )
            )
        except GitCommandError as exc:
            return exc.status != 1  # 1: no such key anywhere
        for line in out.splitlines():
            key, _, value = line.partition(" ")
            if key.endswith(".promisor"):
                # Git reads any non-zero number as true (`2`, `1k`); only what it
                # reads as false is false, so an unknown spelling refuses.
                if value.strip().lower() not in ("false", "no", "off", "0"):
                    return True
            elif value.strip():
                return True
        return False

    def _git(self, extra: Sequence[str] = ()) -> Any:
        """Return the Git command runner, with settings that change what is read pinned.

        `log.follow` would desynchronise `log` from `rev-list`, so results must
        not depend on the user's configuration.

        Args:
            extra: More `name=value` settings for this call only.

        Returns:
            GitPython's command runner for this repository.
        """
        # Pinned off: a repository's config could make Git run gpg.program or an
        # fsmonitor program (ADR 0024). Pinned to Git's defaults: each of the rest,
        # set in a repository, changed line or co-author counts (Git 2.55).
        return self._repo.git(
            c=[
                "log.follow=false",
                "log.showSignature=false",
                "core.fsmonitor=false",
                "status.submoduleSummary=false",
                "log.showRoot=true",
                "diff.renames=true",
                "diff.algorithm=myers",
                "core.bigFileThreshold=512m",
                "trailer.separators=:",
                # Reveille decodes Git's output as UTF-8; a repository must not re-encode it.
                "i18n.logOutputEncoding=UTF-8",
                # Reveille reads `.mailmap` itself; Git's own would open whatever the
                # repository names, and block on a FIFO.
                "log.mailmap=false",
                "mailmap.file=",
                "mailmap.blob=",
                # Read by every diff Git prints, numstat included: a FIFO named here
                # blocks the read for ever. An empty value is refused, so the null file.
                f"diff.orderFile={os.devnull}",
                *extra,
            ]
        )

    def _trailer_stream(self, log_args: list[str], co_authors: bool) -> _LogStream | None:
        """Start the co-author read over the selection `log_args` makes, if it is wanted.

        Args:
            log_args: The main read's arguments.
            co_authors: Whether the caller wants co-authors credited.

        Returns:
            The NUL-separated `git log`, started, or None.
        """
        if not co_authors:
            return None
        return _LogStream(
            self._git().log("-z", _TRAILER_FORMAT, *_selection(log_args), as_process=True),
            separator=b"\0",
        )

    def _trailer_records(self, trailers: _LogStream | None) -> list[str] | GitCommandError | None:
        """Take the co-author read: one record per commit, its hash and trailer values.

        Args:
            trailers: The NUL-separated `git log`, already started, or None.

        Returns:
            The records, Git's failure, which leaves co-authors uncredited, or None
            when nothing was read.
        """
        if trailers is None:
            return None
        try:
            return trailers.records()
        except GitCommandError as exc:
            return exc

    def _paths_never_changed(self, rev: str, paths: Sequence[str]) -> tuple[str, ...]:
        """Return the excluded paths no commit on `rev` ever changed: almost always a typo.

        Args:
            rev: The analysed revision.
            paths: The excluded paths, already normalised.

        Returns:
            The paths that matched nothing, in the order given.

        Raises:
            RepositoryError: If Git cannot answer.
        """
        unmatched: list[str] = []
        for path in paths:
            try:
                found = str(
                    self._git().log(
                        "-1",
                        "--full-history",
                        "--format=%H",
                        "--end-of-options",
                        rev,
                        "--",
                        f":(top,literal){path}",
                    )
                ).strip()
            except GitCommandError as exc:
                raise RepositoryError(
                    f"Failed to check the excluded path '{path}' on '{rev}'. Detail: {exc}"
                ) from exc
            if not found:
                unmatched.append(path)
        return tuple(unmatched)

    def _noreply_accounts(self, rev: str) -> tuple[dict[str, str], dict[str, str]]:
        """Read which GitHub accounts committed, for folding noreply addresses (ADR 0023).

        One pass over author addresses on the branch, newest first, so the first
        username seen for an account number is its current one.

        Args:
            rev: The analysed branch, already checked not to begin with `-`.

        Returns:
            Account number to canonical address, and legacy username to that address
            for usernames only one account used.

        Raises:
            RepositoryError: If Git cannot list the addresses. Going on without them
                would split accounts and narrow an exclusion without a word.
        """
        try:
            out = str(self._git().log("--no-merges", "--format=%ae", "--end-of-options", rev, "--"))
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to read the author addresses on '{rev}'. Detail: {exc}"
            ) from exc
        current: dict[str, str] = {}
        accounts_of: dict[str, set[str]] = defaultdict(set)
        for line in out.splitlines():
            match = _GITHUB_NOREPLY_RE.match(line.strip())
            if match is None:
                continue
            account, username = match.group("account"), match.group("username")
            current.setdefault(account, username)
            accounts_of[username.lower()].add(account)
        accounts = {a: f"{a}+{u}@users.noreply.github.com" for a, u in current.items()}
        usernames = {
            u: accounts[next(iter(ids))] for u, ids in accounts_of.items() if len(ids) == 1
        }
        return accounts, usernames

    def read_state(self) -> RepositoryState:
        """Read the repository's present state (ADR 0024); see `_read_state`.

        Returns:
            The state.

        Raises:
            RepositoryError: If Git fails, as with a corrupt index or a lock.
        """
        try:
            return self._read_state()
        except GitCommandError as exc:
            raise RepositoryError(
                f"Git could not read the repository's state: {_git_error(exc)}"
            ) from exc

    def _read_state(self) -> RepositoryState:
        """Read the repository's present state, changing nothing (ADR 0024).

        Every call runs with optional locks off and fsmonitor pinned off (`_git`), so
        `git status` neither rewrites the index nor runs a program the repository names.

        Returns:
            The branch, work in progress, working tree, stashes, worktrees, branch
            counts and latest tag.
        """
        status = _Status()
        filters = None if self._repo.bare else self._repository_filters()
        unread = not self._repo.bare and filters is None
        if not self._repo.bare and filters is not None:
            # Each driver the repository's own config names is replaced for this
            # call: `git status` runs a clean or process filter to compare files.
            overrides = [
                setting
                for name in filters
                for setting in (
                    f"filter.{name}.clean=cat",
                    f"filter.{name}.smudge=cat",
                    f"filter.{name}.process=",
                    f"filter.{name}.required=false",
                )
            ]
            # GitPython refuses a deadline on Windows rather than run the command.
            deadline = (
                {} if sys.platform == "win32" else {"kill_after_timeout": STATUS_TIMEOUT_SECONDS}
            )
            try:
                raw = str(
                    self._git(overrides).status(
                        "--porcelain=v2",
                        "--branch",
                        "-z",
                        "--untracked-files=normal",
                        "--ignore-submodules=all",
                        **deadline,
                    )
                )
            except GitCommandError as exc:
                # GitPython's own marker when it stopped the command; any other
                # failure is Git's, and is reported as Git's.
                if "Timeout:" not in str(exc.stderr):
                    raise
                # A FIFO where Git reads ignore rules (`.gitignore`, `info/exclude`)
                # blocks the read until something writes to it: forever.
                raise RepositoryError(
                    f"`git status` did not finish within {STATUS_TIMEOUT_SECONDS} seconds and "
                    "was stopped. A named pipe (FIFO) where Git reads ignore rules, such as "
                    "a .gitignore, makes it wait for ever; so can a very large working tree."
                ) from exc
            status = _parse_status(raw)
        else:
            # Bare, or filters unknown: read where HEAD is, compare no files.
            status.head = self.resolve_head_sha()
            try:
                status.branch = str(self._git().symbolic_ref("--short", "HEAD")).strip()
            except GitCommandError:
                status.branch = None
        head_time = self._commit_time(status.head) if status.head else None
        tips = self._branch_tips()
        tag, since_tag = self._latest_tag(status.head)
        return RepositoryState(
            branch=status.branch,
            head=status.head,
            upstream=status.upstream,
            ahead=status.ahead,
            behind=status.behind,
            operation=self._operation_in_progress(),
            conflicted=tuple(status.conflicted),
            staged=tuple(status.staged),
            modified=tuple(status.modified),
            deleted=tuple(status.deleted),
            renamed=tuple(status.renamed),
            untracked=tuple(status.untracked),
            stashes=self._stash_count(),
            worktrees=tuple(self._worktrees()),
            branches=len(tips),
            branches_merged=self._merged_branch_count(status.head),
            branches_quiet=quiet_branches(list(tips.values()), head_time),
            latest_tag=tag,
            commits_since_tag=since_tag,
            last_commit=head_time.date() if head_time else None,
            bare=self._repo.bare,
            shallow=self.is_shallow(),
            filters_not_run=filters or (),
            working_tree_unread=unread,
        )

    def _repository_filters(self) -> tuple[str, ...] | None:
        """Name the content filters the repository's own config defines (ADR 0024).

        Only local and worktree scope, and files they include: global and system
        config are the user's own. None when Git cannot report scopes, or when a
        name holds `=`, which no `-c` override can name; the caller then compares
        no files rather than guess.

        Returns:
            The driver names, or None if they cannot be known or overridden.
        """
        try:
            out = str(
                self._git().config(
                    "--show-scope",
                    "-z",
                    "--get-regexp",
                    # `.*`, not `.+`: `filter=` selects the driver named "".
                    r"^filter\..*\.(clean|smudge|process)$",
                )
            )
        except GitCommandError as exc:
            return () if exc.status == 1 else None
        # -z gives scope NUL key LF value NUL; a subsection may hold spaces.
        fields = out.split("\0")
        names = {
            entry.split("\n", 1)[0].removeprefix("filter.").rsplit(".", 1)[0]
            for scope, entry in zip(fields[::2], fields[1::2], strict=False)
            if scope in ("local", "worktree")
        }
        if any("=" in name for name in names):
            return None
        return tuple(sorted(names))

    def _commit_time(self, sha: str) -> datetime.datetime | None:
        """Return a commit's committer time in UTC, or None if it cannot be read."""
        try:
            out = str(self._git().log("-1", "--format=%ct", "--end-of-options", sha, "--")).strip()
        except GitCommandError:
            return None
        return datetime.datetime.fromtimestamp(int(out), tz=datetime.UTC) if out.isdigit() else None

    def _operation_in_progress(self) -> str | None:
        """Name the operation Git has stopped in, from its own files, or None."""
        git_dir = Path(self._repo.git_dir)
        if (git_dir / "rebase-apply" / "applying").exists():
            return "am"
        markers = (
            ("rebase-merge", "rebase"),
            ("rebase-apply", "rebase"),
            ("MERGE_HEAD", "merge"),
            ("CHERRY_PICK_HEAD", "cherry-pick"),
            ("REVERT_HEAD", "revert"),
            ("BISECT_LOG", "bisect"),
        )
        for name, operation in markers:
            if (git_dir / name).exists():
                return operation
        return None

    def _stash_count(self) -> int:
        """Count stash entries; none when there is no stash."""
        try:
            out = str(self._git().log("--walk-reflogs", "--format=%H", "refs/stash", "--"))
        except GitCommandError:
            return 0
        return len(out.split())

    def _worktrees(self) -> list[Worktree]:
        """List the working trees attached to this repository, the one read marked."""
        try:
            found = _parse_worktrees(str(self._git().worktree("list", "--porcelain", "-z")))
        except GitCommandError:
            try:
                # `-z` needs Git 2.36; older Git gives newline-separated records.
                output = str(self._git().worktree("list", "--porcelain"))
            except GitCommandError:
                return []
            found = _parse_worktrees(output, nul=False)
        return [replace(w, current=_same_directory(w.path, self._repo_path)) for w in found]

    def _branch_tips(self) -> dict[str, datetime.datetime]:
        """Map each local branch to its last commit time (UTC)."""
        out = str(
            self._git().for_each_ref("--format=%(committerdate:unix)%00%(refname)", "refs/heads")
        )
        tips: dict[str, datetime.datetime] = {}
        for line in out.splitlines():
            stamp, _, ref = line.partition("\0")
            if stamp.isdigit():
                tips[ref] = datetime.datetime.fromtimestamp(int(stamp), tz=datetime.UTC)
        return tips

    def _merged_branch_count(self, head: str | None) -> int:
        """Count local branches whose tip the current commit contains."""
        if head is None:
            return 0
        out = str(self._git().for_each_ref(f"--merged={head}", "--format=%(refname)", "refs/heads"))
        return len(out.split())

    def latest_tag(self, rev: str, until: datetime.date | None = None) -> str | None:
        """Return the nearest tag reachable from a revision, or None if there is none.

        Args:
            rev: A commit or branch.
            until: Look from the newest commit dated (UTC) on or before this day
                instead, so the tag is one a brief ending then can start at (ADR 0031).

        Returns:
            The tag name, as repository text.
        """
        try:
            if until is not None:
                before = _git_before(until + datetime.timedelta(days=1))
                bound = [] if before is None else [f"--before={before}"]
                rev = str(self._git().rev_list("-1", *bound, "--end-of-options", rev, "--")).strip()
                if not rev:
                    return None
            return str(
                self._git().describe("--tags", "--abbrev=0", "--end-of-options", rev)
            ).strip()
        except GitCommandError:
            return None

    def _latest_tag(self, head: str | None) -> tuple[str | None, int | None]:
        """Return the nearest reachable tag and the non-merge commits after it."""
        tag = self.latest_tag(head) if head is not None else None
        if head is None or tag is None:
            return None, None
        try:
            count = str(
                self._git().rev_list(
                    # refs/tags/: a tag named like a commit hash would resolve to that commit.
                    "--no-merges",
                    "--count",
                    "--end-of-options",
                    f"refs/tags/{tag}..{head}",
                    "--",
                )
            ).strip()
        except GitCommandError:
            return None, None
        return tag, int(count) if count.isdigit() else None

    def resolve_commit(self, revision: str) -> str:
        """Resolve a tag, branch or commit name to a full commit SHA, locally.

        Args:
            revision: The name the caller gave.

        Returns:
            The 40-character SHA of the commit it names.

        Raises:
            RepositoryError: If it is empty, begins with `-` (git would read an option), or
                names no commit here.
        """
        if not revision:
            raise RepositoryError(
                "An empty revision names no commit: give a tag, branch or commit."
            )
        if revision.startswith("-"):
            raise RepositoryError(
                f"Refusing to use {revision!r} as a revision: a value beginning with '-' "
                "is read by git as an option."
            )
        try:
            sha = str(self._git().rev_parse("--verify", "--quiet", f"{revision}^{{commit}}"))
        except GitCommandError as exc:
            raise RepositoryError(
                f"'{revision}' does not name a commit in this repository."
            ) from exc
        return sha.strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Return whether one commit is reachable from another.

        Args:
            ancestor: A full SHA.
            descendant: A full SHA or a branch name already checked not to begin with `-`.

        Returns:
            True if `ancestor` is in `descendant`'s history.
        """
        try:
            self._git().merge_base("--is-ancestor", ancestor, descendant)
        except GitCommandError as exc:
            if exc.status == 1:
                return False
            raise RepositoryError(f"Could not compare {ancestor} and {descendant}.") from exc
        return True

    def tags_in_range(
        self,
        branch: str | None,
        from_commit: str | None,
        since: datetime.date | None,
        until: datetime.date | None,
    ) -> list[str]:
        """Return the tags whose commit lies in the range, newest commit first.

        Merges count here: a tag on a merge commit is still in the range.

        Args:
            branch: The analysed branch; the active branch if None.
            from_commit: A full SHA; the range starts after it.
            since: Inclusive start date, when the range is a window instead.
            until: Inclusive end date, if any.

        Returns:
            Tag names, as repository text.

        Raises:
            RepositoryError: If Git fails to list them.
        """
        try:
            return self._tags_in_range(branch, from_commit, since, until)
        except GitCommandError as exc:
            raise RepositoryError(f"Git could not list the tags: {_git_error(exc)}") from exc

    def _tags_in_range(
        self,
        branch: str | None,
        from_commit: str | None,
        since: datetime.date | None,
        until: datetime.date | None,
    ) -> list[str]:
        """Do the work of `tags_in_range`, letting Git's errors through."""
        rev = self.branch_revision(branch)
        walk = f"{from_commit}..{rev}" if from_commit is not None else rev
        _, rev_list_args = _build_log_args(walk, since, until, self._supports_since_as_filter())
        order = {
            sha: index
            for index, sha in enumerate(
                str(self._git().rev_list(*[a for a in rev_list_args if a != "--no-merges"])).split()
            )
        }
        refs = str(
            self._git().for_each_ref(
                "--format=%(objectname)%00%(*objectname)%00%(refname:strip=2)", "refs/tags"
            )
        )
        found: list[tuple[int, str]] = []
        for line in refs.splitlines():
            target, peeled, name = [*line.split("\0"), "", "", ""][:3]
            commit = peeled or target
            if commit in order and name:
                found.append((order[commit], name))
        return [name for _, name in sorted(found)]

    def last_changes_before(
        self,
        areas: Sequence[str],
        branch: str | None,
        before_commit: str | None,
        before_date: datetime.date | None,
    ) -> dict[str, datetime.date | None]:
        """Return when each directory last changed before a point, in one pass.

        Exclusions do not apply: this is about the directories, not a person. One
        `git log`, newest first, read until every directory has its answer.
        Renames count on both sides, as a path lookup does.

        Args:
            areas: Directory paths; the root area is never looked up.
            branch: The analysed branch; the active branch if None.
            before_commit: Look at this commit's history (inclusive).
            before_date: Or look at the branch's history before this date.

        Returns:
            Each area and the date (UTC) of the latest non-merge commit before the
            point that changed a file in it, or None.
        """
        found: dict[str, datetime.date | None] = dict.fromkeys(areas)
        remaining = {area for area in areas if area != ROOT_AREA}
        if not remaining:
            return found
        # A path may hold any byte but NUL, so each header carries a value drawn
        # now, which no path written before this read can spell.
        marker = secrets.token_hex(16)
        header_re = re.compile(rb"\x01" + marker.encode() + rb"[0-9a-f]{40} ([0-9]+)")
        args = ["--no-merges", "--no-renames", "--name-only", "-z", f"--format=%x01{marker}%H %ct"]
        if before_commit is not None:
            args += ["--end-of-options", before_commit]
        else:
            rev = self.branch_revision(branch)
            before = None if before_date is None else _git_before(before_date)
            if before is not None:
                args.append(f"--before={before}")
            args += ["--end-of-options", rev]
        try:
            process = self._git().log(*args, "--", as_process=True)
        except GitCommandError:
            return found
        silence = _Silence(process.proc)
        try:
            when: datetime.date | None = None
            pending = b""
            for chunk in iter(lambda: process.stdout.read(1 << 16), b""):
                silence.heard()
                *tokens, pending = (pending + chunk).split(b"\0")
                for token in tokens:
                    header = header_re.fullmatch(token)
                    if header is not None:
                        stamp = int(header.group(1))
                        when = datetime.datetime.fromtimestamp(stamp, tz=datetime.UTC).date()
                        continue
                    path = token.lstrip(b"\n").decode("utf-8", "replace")
                    # An area a path is in is one of its prefixes ending at a `/`, or
                    # the path itself: looked up, not compared with every area.
                    for area in _directory_prefixes(path) & remaining:
                        found[area] = when
                        remaining.discard(area)
                if not remaining:
                    break
        finally:
            # Stop Git once every area is answered; reading on would only cost time.
            silence.stop()
        return found

    def last_commit_date(self, until: datetime.date) -> datetime.date | None:
        """Return the date of the last non-merge commit on or before `until`.

        Only the commit dates are read: what `read_commits` with no window would
        give as its latest commit's date, without the names, the trust check or
        the exclusions.

        Args:
            until: The last day counted, in UTC.

        Returns:
            The date, or None when the branch has no such commit.
        """
        log_args, _ = _build_log_args(self._active_revision(), None, until, line_counts=False)
        log_args[log_args.index(_LOG_FORMAT)] = "--format=%ct"
        try:
            output = str(self._git().log(*log_args))
        except GitCommandError:
            return None
        latest: datetime.date | None = None
        for value in set(output.split()):
            try:
                day = datetime.datetime.fromtimestamp(int(value), tz=datetime.UTC).date()
            except (ValueError, OverflowError, OSError):
                continue  # skipped as read_commits skips it
            latest = day if latest is None else max(latest, day)
        return latest

    def resolve_head_sha(self, branch: str | None = None) -> str | None:
        """Return the full SHA at the tip of the analysed ref, pinning the report.

        Args:
            branch: The ref to resolve; the active branch if None.

        Asked of Git: GitPython reads ref files itself, and a reftable
        repository has none, so it said every ref was unresolvable.

        Returns:
            The 40-character SHA, or None if the ref cannot be resolved.
        """
        rev = self.branch_revision(branch)
        try:
            sha = self._git().rev_parse(
                "--quiet", "--verify", "--end-of-options", f"{rev}^{{commit}}"
            )
        except GitCommandError:
            return None
        return str(sha).strip()

    def _addresses_in_history(
        self, rev: str, mailmap: _Mailmap, exclude_set: set[str]
    ) -> dict[str, set[str]]:
        """Return, for each exclusion value, the addresses it reaches in all history.

        A person's other names may lie outside the window or path (ADR 0020), so
        every reachable commit is read. A forged field can only remove more.

        Args:
            rev: The analysed revision.
            mailmap: Parsed `.mailmap` lookup tables.
            exclude_set: Lowercased names and addresses to drop.

        Returns:
            Each matching value and its addresses; empty when nothing is excluded.

        Raises:
            RepositoryError: If Git cannot read either part of the history. An
                exclusion that cannot be checked in full is refused, not applied
                to part of it.
        """
        reached: dict[str, set[str]] = {}
        if not exclude_set:
            return reached
        try:
            raw = str(self._git().log("-z", "--format=%an%x1f%ae", "--end-of-options", rev, "--"))
        except GitCommandError as exc:
            raise _exclusion_unreadable(rev, exc) from exc
        for record in raw.split("\0"):
            fields = record.split(_FIELD_SEP)
            if len(fields) != 2:
                continue
            _, address, hits = _identity(fields[0], fields[1], mailmap, exclude_set)
            for value in hits:
                reached.setdefault(value, set()).add(address.lower())
        # A person may appear only as a co-author, under several names: a name
        # reaches the addresses it carries there too.
        try:
            trailers = str(
                self._git().log(
                    "-z",
                    "--format=%(trailers:key=Co-authored-by,valueonly,unfold,separator=%x1f)",
                    "--end-of-options",
                    rev,
                    "--",
                )
            )
        except GitCommandError as exc:
            raise _exclusion_unreadable(rev, exc) from exc
        for value in trailers.replace("\0", _FIELD_SEP).split(_FIELD_SEP):
            parsed = _co_author_value(_strip_control_chars(value[: _MAX_TRAILER_VALUE + 1]))
            if parsed is None:
                continue
            _, address, hits = _identity(parsed[0], parsed[1].strip(), mailmap, exclude_set)
            for value_hit in hits:
                reached.setdefault(value_hit, set()).add(address.lower())
        return reached

    def history_not_followed(self) -> tuple[int, bool]:
        """Report the history substitutions present and not followed (ADR 0018).

        Plain `git log` follows them, so a reader comparing needs to know.

        Returns:
            The count of `refs/replace/` refs and whether `info/grafts` exists;
            `(0, False)` when Git cannot say.
        """
        try:
            listed = str(self._git().for_each_ref("--format=%(refname)", "refs/replace/"))
            # Not `--git-path`: it honours our GIT_GRAFT_FILE, the null device.
            common = Path(str(self._git().rev_parse("--git-common-dir")).strip())
        except GitCommandError:
            return 0, False
        if not common.is_absolute():
            common = self._repo_path / common
        grafts = common / "info" / "grafts"
        return len([line for line in listed.splitlines() if line.strip()]), grafts.is_file()

    def is_shallow(self) -> bool:
        """Report whether the repository is a shallow clone, so figures are partial.

        Returns:
            True when Git reports a shallow repository, False when it reports not.

        Raises:
            RepositoryError: If Git cannot say. "Not shallow" would then be a guess,
                and a shallow clone's figures would read as the whole history.
        """
        try:
            answer = str(self._git().rev_parse("--is-shallow-repository")).strip()
        except GitCommandError as exc:
            raise RepositoryError(
                f"Git could not say whether this is a shallow clone: {_git_error(exc)}"
            ) from exc
        if answer not in ("true", "false"):
            raise RepositoryError(
                f"Git could not say whether this is a shallow clone: it answered {answer!r}."
            )
        return answer == "true"

    @property
    def file_stats(self) -> tuple[FileStats, ...]:
        """Per-path activity from the most recent `read_commits` call, replaced each call.

        Returns:
            One `FileStats` per distinct path, in first-seen order.
        """
        return self._file_stats

    @property
    def mailmap_applied(self) -> bool:
        """Whether a non-empty `.mailmap` was applied; False until `read_commits` runs.

        Identity merging changes counts, so reports with and without differ.
        """
        return self._mailmap_applied

    def _git_version(self) -> tuple[int, int] | None:
        """Return the installed Git's major and minor version, or None if unreadable."""
        return _installed_git_version()

    def _supports_since_as_filter(self) -> bool:
        """Whether the installed git (2.37 or newer) understands `--since-as-filter`.

        Probed: older git falls back, possibly under-reporting non-linear history.

        Returns:
            True when git is 2.37 or newer.
        """
        version = self._git_version()
        return version is not None and version >= (2, 37)

    def _resolve_remote_url(self) -> str | None:
        """Return the origin (or first) remote's URL, credentials removed.

        Returns:
            The remote URL string, or None if no remotes are configured.
        """
        if not self._repo.remotes:
            return None
        try:
            url = str(self._repo.remotes["origin"].url)
        except IndexError:
            url = str(self._repo.remotes[0].url)
        return _without_credentials(url)

    def _working_mailmap(self) -> str | None:
        """Return the working tree's `.mailmap`, bounded by `_MAX_MAILMAP_BYTES`.

        Returns:
            The text, undecodable bytes replaced; None if absent, unreadable,
            a symbolic link, or too large.
        """
        mailmap_path = self._repo_path / ".mailmap"
        # Git refuses a symlinked .mailmap; one could point at /dev/zero.
        if mailmap_path.is_symlink() or not mailmap_path.is_file():
            return None
        try:
            # Read one byte past the limit: the file can grow after a size check.
            with mailmap_path.open("rb") as handle:
                raw = handle.read(_MAX_MAILMAP_BYTES + 1)
        except OSError as exc:
            # Said, not skipped: unmerged identities change every count. No path, which can
            # hold a login name.
            _logger.warning(
                "The working-tree .mailmap could not be read (%s) and was not applied.",
                exc.strerror or type(exc).__name__,
            )
            return None
        if len(raw) > _MAX_MAILMAP_BYTES:
            _logger.warning(
                "The working-tree .mailmap is over the %s-byte limit and was not read.",
                f"{_MAX_MAILMAP_BYTES:,}",
            )
            return None
        # U+FFFD, not an exception: exit 1 means a negative answer, not a crash.
        return raw.decode("utf-8", errors="replace")

    def _committed_mailmap(self) -> str | None:
        """Return the `.mailmap` committed at HEAD, as Git reads it in a bare repository.

        Returns:
            The blob's text, undecodable bytes replaced; None if there is no
            such blob, HEAD is unborn, or it exceeds `_MAX_MAILMAP_BYTES`.
        """
        try:
            size = int(str(self._git().cat_file("-s", "HEAD:.mailmap")).strip())
            if size > _MAX_MAILMAP_BYTES:
                _logger.warning(
                    "The .mailmap committed at HEAD is %s bytes, over the %s-byte limit, "
                    "and was not read.",
                    f"{size:,}",
                    f"{_MAX_MAILMAP_BYTES:,}",
                )
                return None
            raw = self._git().cat_file("blob", "HEAD:.mailmap", stdout_as_string=False)
        except (GitCommandError, ValueError):
            return None
        return bytes(raw).decode("utf-8", errors="replace")

    def _read_mailmap(self) -> _Mailmap:
        """Read and parse the repository's `.mailmap` (all four gitmailmap(5) forms).

        Malformed lines are skipped: one bad hand-edited line should not stop a report.

        Returns:
            The parsed lookup tables; empty if there is no readable file.
        """
        text = self._committed_mailmap() if self._repo.bare else self._working_mailmap()
        if text is None:
            return _Mailmap()
        lines = text.splitlines()

        mailmap = _Mailmap()
        for line in lines:
            fields = _parse_mailmap_line(line)
            if fields is None:
                continue
            proper_name, proper_email, commit_name, commit_email = fields
            if commit_name is not None:
                # Keyed on name and address, a later line replaces the entry whole.
                mailmap.by_name_and_email[(commit_name.lower(), commit_email.lower())] = (
                    proper_name,
                    (proper_email or commit_email).lower(),
                )
                continue
            # Keyed on the address alone, a later line replaces only the fields it
            # gives. Both as Git's add_mapping does.
            key = commit_email.lower()
            earlier_name, earlier_email = mailmap.by_email.get(key, (None, key))
            mailmap.by_email[key] = (
                proper_name if proper_name is not None else earlier_name,
                proper_email.lower() if proper_email is not None else earlier_email,
            )

        return mailmap


#: Hash, then each `Co-authored-by` value, unfolded; used with `-z`.
_TRAILER_FORMAT = (
    f"--format=%H{_FIELD_SEP}"
    f"%(trailers:key=Co-authored-by,valueonly,unfold,separator=%x{ord(_FIELD_SEP):02x})"
)

#: Distinct co-authors kept per commit, bounding hostile messages.
_MAX_CO_AUTHORS = 32

#: Longest `Co-authored-by` value read; a real one is a name and an address.
_MAX_TRAILER_VALUE = 4096


def _co_author_value(value: str) -> tuple[str, str] | None:
    """Split `Name <address>` in one pass: the address is the last `<...>`, ending the value.

    A regular expression for this backtracked quadratically on a long run of
    spaces; this reads the value once, and a value over `_MAX_TRAILER_VALUE`
    characters is skipped.

    Args:
        value: One trailer value, control characters removed.

    Returns:
        The name (possibly empty) and the address, or None if malformed.
    """
    text = value.strip()
    if len(text) > _MAX_TRAILER_VALUE or not text.endswith(">"):
        return None
    left = text.rfind("<")
    email = text[left + 1 : -1] if left >= 0 else ""
    if not email or ">" in email:
        return None
    return text[:left].strip(), email


def _co_author_identities(
    values: str,
    mailmap: _Mailmap,
    exclude_set: set[str],
    matched: set[str],
    author: str,
) -> tuple[tuple[tuple[str, str], ...], int]:
    """Resolve one commit's `Co-authored-by` values like author identities.

    Args:
        values: The trailer values, separated by the field separator.
        mailmap: Parsed `.mailmap`.
        exclude_set: Lowercased exclusions.
        matched: Mutated with every exclusion value that matched.
        author: The commit's own author address, lowercased.

    Returns:
        Up to `_MAX_CO_AUTHORS` distinct `(name, address)` pairs, and how
        many more distinct co-authors were ignored.
    """
    found: dict[str, str] = {}
    dropped = 0
    for value in values.split(_FIELD_SEP):
        parsed = _co_author_value(_strip_control_chars(value[: _MAX_TRAILER_VALUE + 1]))
        if parsed is None:
            continue
        raw_name, raw_email = parsed[0], parsed[1].strip()
        name, email = _resolve_identity(raw_name, raw_email, mailmap)
        name = _strip_invisible(_strip_control_chars(name))
        email = _strip_control_chars(email).lower()
        hits = exclude_set & {_match_key(v) for v in (name, email, raw_name, raw_email)}
        if hits:
            matched.update(hits)
            continue
        name = _truncate(name, _MAX_NAME_LENGTH)
        email = _truncate(email, _MAX_EMAIL_LENGTH)
        if email == author or email in found:
            continue
        if len(found) == _MAX_CO_AUTHORS:
            dropped += 1
            continue
        found[email] = name or email
    return tuple((name, email) for email, name in found.items()), dropped


def _count_commits(n: int) -> str:
    """Return "1 commit" or "N commits"."""
    return f"{n:,} commit" if n == 1 else f"{n:,} commits"


def _unreadable(
    well_formed: AbstractSet[str],
    authentic_shas: AbstractSet[str],
    undatable: AbstractSet[str] = frozenset(),
) -> int:
    """Count the commits whose record could not be read, and say so (ADR 0019).

    Args:
        well_formed: The names `_well_formed_shas` gave for the main read's records.
        authentic_shas: Object names git reported for this revision.
        undatable: Commits whose timestamp no date can hold.

    Returns:
        How many authentic commits had no well-formed record or no usable date.
    """
    unreadable = len((authentic_shas - well_formed) | undatable)
    if unreadable:
        _logger.warning(
            "%s could not be read and %s not counted: an author field held "
            "characters the read splits on, or a date no calendar holds.",
            _count_commits(unreadable),
            "is" if unreadable == 1 else "are",
        )
    return unreadable


class _LogStream:
    """One `git log` read in the background, split into records as it arrives.

    Git writes the log while the reader runs its other queries, and the output is
    never held whole: the records are kept as bytes until they are taken, so one
    non-ASCII name cannot double the size of every other record in memory.

    The threads only read pipes. GitPython's runner keeps the pinned `-c`
    settings on one shared object between calls, so a Git call from a second
    thread could run without them.
    """

    def __init__(self, process: Any, separator: bytes = _RECORD_SEP_BYTES) -> None:
        """Start reading the process's output.

        Args:
            process: GitPython's handle on a running `git log`.
            separator: The byte between records.
        """
        self._process = process
        self._silence = _Silence(process.proc)
        self._separator = separator
        self._records: list[bytes] = []
        self._stderr: list[bytes] = []
        self._failure: BaseException | None = None
        self._threads = [
            threading.Thread(target=self._reading, args=(self._split,), daemon=True),
            # Read too, so warnings Git writes cannot fill the pipe and stop it.
            threading.Thread(target=self._reading, args=(self._drain_stderr,), daemon=True),
        ]
        try:
            for thread in self._threads:
                thread.start()
        except BaseException:
            self._stop()
            raise

    def _reading(self, read: Callable[[], None]) -> None:
        """Run one reader; if it fails, keep the failure and stop Git.

        Stopped, Git cannot wait for ever on a pipe nobody reads, and the
        failure is raised where the records are taken, not lost with the thread.

        Args:
            read: The reader to run.
        """
        try:
            read()
        except BaseException as exc:  # raised again by raw_records
            self._failure = self._failure or exc
            self._stop()

    def _stop(self) -> None:
        """Stop Git if it is still running."""
        if self._process.proc.poll() is None:
            with contextlib.suppress(OSError):
                self._process.proc.kill()

    def _split(self) -> None:
        """Read the output to its end, one record per separator."""
        pieces: list[bytes] = []
        for chunk in iter(lambda: self._process.proc.stdout.read(1 << 16), b""):
            self._silence.heard()
            parts = chunk.split(self._separator)
            pieces.append(parts[0])
            if len(parts) > 1:
                self._records.append(b"".join(pieces))
                self._records.extend(parts[1:-1])
                pieces = [parts[-1]]
        self._records.append(b"".join(pieces))

    def _drain_stderr(self) -> None:
        """Read Git's error output to its end."""
        self._stderr.append(self._process.proc.stderr.read())

    def raw_records(self) -> list[bytes]:
        """Wait for Git and return the records as Git wrote them.

        Returns:
            The records, the bytes before the first separator first.

        Raises:
            GitCommandError: If Git exits with an error, or its output could not
                be read to the end.
            RepositoryError: If Git wrote nothing for `GIT_TIMEOUT_SECONDS` and
                was stopped; not a GitCommandError, so no caller takes it for a
                failure it can read past.
        """
        for thread in self._threads:
            thread.join()
        status = self._process.proc.wait()
        if self._silence.expired:
            raise _timed_out("git log")
        if self._failure is not None:
            raise GitCommandError(
                self._process.args, status, f"its output could not be read: {self._failure!r}"
            ) from self._failure
        if status != 0:
            raise GitCommandError(self._process.args, status, b"".join(self._stderr))
        records, self._records = self._records, []
        return records

    def records(self) -> list[str]:
        """Wait for Git and return the records, decoded as GitPython decodes output.

        Returns:
            The records, the text before the first separator first.

        Raises:
            GitCommandError: If Git exits with an error.
        """
        return [safe_decode(record) for record in self.raw_records()]

    def close(self) -> None:
        """Stop Git if it is still running, and wait for the readers."""
        self._stop()
        self._process.proc.wait()
        for thread in self._threads:
            thread.join()


def _well_formed_shas(
    records: Sequence[bytes], authentic_shas: Mapping[str, str]
) -> dict[str, str]:
    """Return the object names whose log record has the expected shape.

    A record split by injected separators fails this check, so its commit is
    counted as unreadable rather than lost silently (ADR 0019).

    Args:
        records: The main read's records, as Git wrote them.
        authentic_shas: Object names git reported for this revision.

    Returns:
        The names of commits with exactly one record that has five fields, the
        same authentic name at both ends.
    """
    seen: dict[str, int] = {}
    for record in records:
        # Only the header is decoded: a newline is one byte in UTF-8, never part of another.
        fields = safe_decode(record.partition(b"\n")[0]).split(_FIELD_SEP)
        if len(fields) == 5 and fields[0] == fields[4] and fields[0] in authentic_shas:
            seen[fields[0]] = seen.get(fields[0], 0) + 1
    # A hash with two well-formed records has one forged copy, and nothing says
    # which: neither is trusted, and the commit is counted as unreadable.
    return {sha: authentic_shas[sha] for sha, count in seen.items() if count == 1}


def _shared_trailer_records(
    records: list[str] | GitCommandError | None, canonical: Mapping[str, str]
) -> list[str] | GitCommandError | None:
    """Keep a co-author record that credits nobody as its hash alone, the shared string.

    Almost every commit has no trailer; otherwise its record is a second copy of
    its hash, held for the whole read. The order, which `_credit_co_authors` checks
    against `rev-list`, is kept, and a record whose hash Git did not list is kept
    whole, so it still fails that check.

    Args:
        records: The co-author log's records, Git's failure to give them, or None.
        canonical: Each hash `rev-list` listed, to the string the read shares.

    Returns:
        The records, the same in number and order.
    """
    if not isinstance(records, list):
        return records
    for index, record in enumerate(records):
        sha, separator, values = record.partition(_FIELD_SEP)
        if separator and not values.strip():
            records[index] = canonical.get(sha.strip(), record)
    return records


def _state_wide_exclusions(reached: dict[str, set[str]]) -> None:
    """Warn when a name reached more than one address (ADR 0020).

    A shared name removes both people; the warning makes that visible.

    Args:
        reached: Each exclusion value and the addresses it matched.
    """
    for value, addresses in sorted(reached.items()):
        if len(addresses) > 1:
            _logger.warning(
                "--exclude-author %r matched %d addresses, and every commit under each "
                "was excluded: %s. Give an address to exclude only one.",
                value,
                len(addresses),
                ", ".join(sorted(addresses)),
            )


#: The largest `.mailmap` read, in bytes; a real one is kilobytes.
_MAX_MAILMAP_BYTES = 1_048_576


#: How long `state` lets `git status` run before stopping it (a FIFO makes it wait for ever).
STATUS_TIMEOUT_SECONDS = 120

#: How long any other Git command may run, or a history read go without output, before it
#: is stopped. A named pipe or a device anywhere Git opens a file makes it wait for ever, and
#: no list of such files is complete; this bounds the wait whatever the file.
GIT_TIMEOUT_SECONDS = 300


def _timed_out(command: object) -> RepositoryError:
    """The error for a Git command stopped at its deadline."""
    return RepositoryError(
        f"Git did not finish ({command}) within {GIT_TIMEOUT_SECONDS} seconds and was "
        "stopped. A named pipe (FIFO) or a device where Git reads a file makes it wait for "
        "ever. Remove it, or run Reveille on a fresh clone."
    )


class _TimedGit(Git):
    """GitPython's runner, with a deadline on every command it waits for.

    GitPython stops a command at its deadline with SIGKILL, and first lists the
    command's children with `pgrep` (or `ps`) to stop them too. It cannot do
    this on Windows, where the deadline is not set.
    """

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Run a command as `Git.execute` does, stopping it at `GIT_TIMEOUT_SECONDS`.

        A command started as a process is not waited for here; its reader keeps
        the deadline (`_Silence`). A caller's own deadline is kept, and so is the
        error it gets.

        GitPython (3.2.1) cancels its deadline timer only when the wait returns.
        Interrupted, the timer outlives the command, and the interpreter waits for
        it before exiting: Ctrl-C took the full deadline to take effect.
        """
        running = set(threading.enumerate())
        try:
            return self._execute_timed(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            for thread in set(threading.enumerate()) - running:
                if isinstance(thread, threading.Timer):
                    thread.cancel()
            raise

    def _execute_timed(self, *args: Any, **kwargs: Any) -> Any:
        """Run the command, with `GIT_TIMEOUT_SECONDS` unless a deadline is given."""
        timed = (
            sys.platform != "win32"
            and not kwargs.get("as_process")
            and kwargs.get("kill_after_timeout") is None
        )
        if not timed:
            return super().execute(*args, **kwargs)
        try:
            return super().execute(*args, kill_after_timeout=GIT_TIMEOUT_SECONDS, **kwargs)
        except GitCommandError as exc:
            if "Timeout:" in str(exc.stderr):
                raise _timed_out(" ".join(map(str, exc.command))) from exc
            raise


class _TimedRepo(Repo):
    """A repository whose Git commands run with a deadline."""

    GitCommandWrapperType = _TimedGit


class _Silence:
    """Stop a Git process that has written nothing for `GIT_TIMEOUT_SECONDS`.

    A history read can rightly run for minutes on a long history, but it writes
    as it goes; one that writes nothing for that long is waiting on a file.
    """

    def __init__(self, process: Any) -> None:
        """Start watching.

        Args:
            process: The `subprocess.Popen` of a running Git command.
        """
        self._process = process
        self._last = time.monotonic()
        self.expired = False
        threading.Thread(target=self._watch, daemon=True).start()

    def heard(self) -> None:
        """Note that the process wrote something."""
        self._last = time.monotonic()

    def stop(self) -> None:
        """Stop the process, read or not, and raise if it was stopped for its silence.

        Raises:
            RepositoryError: If it wrote nothing for `GIT_TIMEOUT_SECONDS`.
        """
        with contextlib.suppress(OSError):
            self._process.kill()
        self._process.wait()
        if self.expired:
            raise _timed_out("git log")

    def _watch(self) -> None:
        while self._process.poll() is None:
            idle = time.monotonic() - self._last
            if idle >= GIT_TIMEOUT_SECONDS:
                self.expired = True
                with contextlib.suppress(OSError):
                    self._process.kill()
                return
            time.sleep(min(1.0, GIT_TIMEOUT_SECONDS - idle))


_GIT_VERSION_LOCK = threading.Lock()


def _installed_git_version() -> tuple[int, int] | None:
    """Return the installed Git's major and minor version, or None if unreadable.

    Read once per process, since it depends on no repository. Locked, because
    `repos` opens readers on several threads, and each would otherwise ask
    before the first answer is cached.
    """
    with _GIT_VERSION_LOCK:
        return _read_git_version()


@functools.cache
def _read_git_version() -> tuple[int, int] | None:
    """Ask Git its version; called only by `_installed_git_version`."""
    try:
        raw = str(_TimedGit().version())
    except Exception:  # a missing or broken git binary is reported by the first read
        return None
    match = re.search(r"(\d+)\.(\d+)", raw)
    return (int(match.group(1)), int(match.group(2))) if match else None


def find_repositories(directory: Path, depth: int) -> tuple[list[Path], list[Path]]:
    """Find the Git repositories under `directory`, to `depth` levels (ADR 0026).

    A working tree holds `.git` (a directory, or the file a linked worktree or
    submodule has); a bare repository holds `HEAD`, `objects` and `refs`. A
    repository found is not searched further, and a symbolic link is not
    followed, so the search stays inside `directory`. No Git command runs.

    Args:
        directory: Where to search; not itself a candidate.
        depth: How many levels below it, 1 to `MAX_SEARCH_DEPTH`.

    Returns:
        The repositories, and the directories that could not be listed, each sorted.
    """
    found: list[Path] = []
    unreadable: list[Path] = []
    level = [directory]
    for _ in range(min(max(depth, 1), MAX_SEARCH_DEPTH)):
        below: list[Path] = []
        for parent in level:
            try:
                entries = sorted(os.scandir(parent), key=lambda e: e.name)
            except OSError:
                unreadable.append(parent)
                continue
            for entry in entries:
                if entry.name == ".git" or entry.is_symlink() or not entry.is_dir():
                    continue
                candidate = Path(entry.path)
                if is_repository(candidate):
                    found.append(candidate)
                elif not os.access(candidate, os.X_OK):
                    # Nothing inside can be looked at, so it may be a repository; at the
                    # last level it was left out without a word.
                    unreadable.append(candidate)
                else:
                    below.append(candidate)
        level = below
    # A Git directory a working tree here uses (`git init --separate-git-dir`) is
    # that working tree's, so it is not a row of its own. One nothing uses stays.
    used = {_git_directory_of(tree) for tree in found}
    found = [path for path in found if path.resolve() not in used]
    return sorted(found), sorted(unreadable)


def _refuse_what_git_cannot_open(repo_path: Path, exc: GitCommandError) -> NoReturn:
    """Say why Git cannot open a repository, in its own words where Reveille has none.

    Args:
        repo_path: The repository given.
        exc: Git's refusal.

    Raises:
        RepositoryError: Always.
    """
    # Git refuses a repository another user owns, and GitPython then reads
    # its HEAD as unborn: "no commits" would be a wrong answer.
    if "dubious ownership" in str(exc.stderr):
        raise RepositoryError(
            f"Git refuses to read '{repo_path}': another user owns it. If you "
            "trust it, add it to Git's safe.directory setting "
            "(git config --global --add safe.directory <path>)."
        ) from exc
    if "safe.bareRepository" in str(exc.stderr):
        # The caller's own setting refuses a bare repository found by searching.
        raise RepositoryError(
            f"Git refuses to read '{repo_path}': it is a bare repository, and your "
            "safe.bareRepository setting is 'explicit'. Clone it (git clone <path>) and give "
            "the clone."
        ) from exc
    if not os.path.lexists(repo_path / ".git") and is_repository(repo_path):
        # A Git directory not configured as bare, such as the store that
        # `git init --separate-git-dir` makes: Git looks for its working tree.
        raise RepositoryError(
            f"'{repo_path}' holds a Git directory but no working tree, and its "
            "configuration does not say it is bare (core.bare is not true). Give the "
            "working tree whose `.git` names this directory."
        ) from exc
    raise RepositoryError(f"Git cannot read '{repo_path}': {exc.stderr.strip()}") from exc


#: A `.git` file holds one `gitdir:` line, a path; more than a path's length is not one.
_MAX_GITFILE_BYTES = 4096


def _git_directory_of(tree: Path) -> Path | None:
    """Return the Git directory a working tree's `.git` names, by its files alone.

    A `.git` directory is its own; a symbolic link is resolved; a `.git` file is
    read for its `gitdir:` line, relative to the tree when not absolute.
    """
    dotgit = tree / ".git"
    try:
        if dotgit.is_symlink() or dotgit.is_dir():
            return dotgit.resolve()
        # Opened without waiting, so a named pipe here does not hold the search (it
        # reads as empty), and read to a bound, so a device cannot read for ever.
        descriptor = os.open(dotgit, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            line = handle.read(_MAX_GITFILE_BYTES).split(b"\n", 1)[0].decode()
    except (OSError, UnicodeDecodeError):
        return None
    if not line.startswith("gitdir: "):
        return None
    return (tree / line.removeprefix("gitdir: ").strip()).resolve()


def main_worktree_of(tree: Path) -> Path | None:
    """Return the main working tree of a linked worktree, by its files alone.

    A linked worktree's Git directory holds `commondir`, naming the main one's
    Git directory; the main tree is that directory without a trailing `.git`, as
    `git worktree list` gives it (a bare repository is its own). No Git command runs.

    Args:
        tree: A working tree.

    Returns:
        The main working tree, resolved, or None for a tree that is not a linked
        worktree or whose files cannot be read.
    """
    git_directory = _git_directory_of(tree)
    if git_directory is None:
        return None
    try:
        with (git_directory / "commondir").open("rb") as handle:
            line = handle.read(_MAX_GITFILE_BYTES).split(b"\n", 1)[0].decode().strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not line:
        return None
    common = (git_directory / line).resolve()
    return common.parent if common.name == ".git" else common


def is_repository(path: Path) -> bool:
    """Return whether `path` is a working tree or a bare repository, by its files alone.

    A `.git` that is a symbolic link counts, as a `.git` file does: it names the
    repository's own Git directory, as Git reads it, and the search does not enter it.
    """
    try:
        if os.path.lexists(path / ".git"):
            return True
        return (
            (path / "HEAD").is_file() and (path / "objects").is_dir() and (path / "refs").is_dir()
        )
    except OSError:
        return False


def repository_root(path: Path) -> Path:
    """Return the top of the working tree `path` lies in, as Git finds it.

    Git searches upwards, stopping at `GIT_CEILING_DIRECTORIES` and refusing a
    repository another user owns. A bare repository, a path Git finds no
    working tree for, or one it cannot search is returned unchanged, so the
    reader reports it.

    Args:
        path: A directory given as `--repo`, or the working directory.

    Returns:
        The working tree's top directory, or `path` resolved.
    """
    if not path.is_dir():
        return path.resolve()
    # A variable that points Git at another repository (a hook sets GIT_DIR)
    # would redirect the search, and GitPython cannot unset one: search only
    # without them, so `--repo` alone names the repository.
    if _REPOSITORY_VARIABLES & os.environ.keys():
        return path.resolve()
    try:
        _refuse_git_files_that_block(path, search_up=True)
    except RepositoryError:
        return path.resolve()  # the reader opens it, and says why it refuses
    try:
        # `-C`, not a working directory: GitPython runs Git in the process's own
        # directory when the one it is given cannot be entered.
        top = str(
            _TimedGit().execute(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
        ).strip()
        git_dir = _absolute_git_dir(path)
    except (GitCommandError, OSError):
        return path.resolve()
    if not top or git_dir is None:
        return path.resolve()
    # `core.worktree` can name another repository's directory: from there, Git
    # finds that one's Git directory, not this one's. Return the repository the
    # path is in, so the reader refuses it, rather than the other repository.
    if _absolute_git_dir(Path(top)) != git_dir:
        return Path(git_dir).parent.resolve() if Path(git_dir).name == ".git" else path.resolve()
    return Path(top).resolve()


#: Files Git, or GitPython, reads in a Git directory before anything else.
_GIT_DIR_FILES = (
    "HEAD",
    "config",
    "config.worktree",
    "commondir",
    "packed-refs",
    "shallow",
    "objects/info/alternates",
)

#: Larger than any configuration a person writes: a regular file this size is refused
#: too, as GitPython reads the whole of one, includes and all.
_MAX_GIT_FILE_BYTES = 8 * 1024 * 1024

#: Files that grow with the repository (one line per ref, or per shallow boundary): only a
#: pipe or a device there is refused, never a size.
_UNBOUNDED_GIT_DIR_FILES = ("packed-refs", "shallow")

#: Git follows `include.path` at most this deep.
_MAX_INCLUDE_DEPTH = 10


def _refuse_git_files_that_block(start: Path, *, search_up: bool) -> None:
    """Refuse a repository whose Git directory would make a read wait or grow for ever.

    Git and GitPython read these files before anything else. A named pipe makes
    them wait for ever; a device such as `/dev/zero` feeds GitPython's config
    reader without end; an `include.path` can name either, `/dev/stdin` included.
    A copied directory or an archive can carry one; `git clone` cannot. Checked
    before Git runs at all, so nothing here starts a read that could block.

    Args:
        start: The directory given.
        search_up: Whether to look for the Git directory in its parents too, as
            Git's own search does.

    Raises:
        RepositoryError: If one of those files is not a regular file, or is larger
            than any configuration a person writes.
    """
    # Absolute, so the search can go up from a relative path such as `.`.
    git_dir = _git_dir_of(Path(os.path.abspath(start)), search_up=search_up)
    if git_dir is None:
        return
    directories = [git_dir]
    if _checked(git_dir / "commondir"):
        common = git_dir / (git_dir / "commondir").read_text("utf-8", "replace").strip()
        directories.append(common)
    configs: list[Path] = []
    for directory in directories:
        for name in _GIT_DIR_FILES:
            bounded = name not in _UNBOUNDED_GIT_DIR_FILES
            if _checked(directory / name, bounded=bounded) and name.startswith("config"):
                configs.append(directory / name)
    for config in configs:
        _check_includes(config, 0)
    # GitPython reads refs and loose objects in Python, where no deadline reaches;
    # `state` reads the index, the reflogs and every worktree's HEAD.
    for directory in dict.fromkeys(directories):
        _checked(directory / "index", bounded=False)
        for name in ("refs", "logs", "worktrees"):
            _refuse_special_files(directory / name)
        for objects in _object_directories(directory / "objects"):
            _refuse_special_files(objects)


#: Git follows alternates at most this deep.
_MAX_ALTERNATES_DEPTH = 5


def _object_directories(objects: Path) -> list[Path]:
    """Return an object directory and every one its alternates name, as Git follows them.

    Args:
        objects: The repository's `objects` directory.

    Returns:
        The directories, the repository's own first.

    Raises:
        RepositoryError: If an alternates file is not a regular file, or is too large.
    """
    found: list[Path] = []
    pending = [(objects, 0)]
    while pending:
        directory, depth = pending.pop(0)
        try:
            is_directory = directory.is_dir()
        except OSError:
            continue  # unreadable: Git cannot read objects there either, and the reader says why
        if directory in found or not is_directory:
            continue
        found.append(directory)
        alternates = directory / "info" / "alternates"
        if depth >= _MAX_ALTERNATES_DEPTH or not _checked(alternates):
            continue
        for line in alternates.read_text("utf-8", "replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                target = Path(line.strip('"'))
                pending.append((target if target.is_absolute() else directory / target, depth + 1))
    return found


def _refuse_special_files(root: Path) -> None:
    """Refuse a named pipe, a device or a socket anywhere under `root`.

    Only the type is checked, not the size: a pack can rightly be gigabytes. A
    link to a directory is followed, as Git follows it; each directory is
    walked once, so a loop of links cannot hold the walk.

    Args:
        root: A directory Git or GitPython reads files from, such as `refs`.

    Raises:
        RepositoryError: If a file under it is not a regular file.
    """
    pending = [root]
    walked: set[tuple[int, int]] = set()
    while pending:
        directory = pending.pop()
        try:
            identity = directory.stat()
            entries = list(os.scandir(directory))
        except OSError:
            continue
        if (identity.st_dev, identity.st_ino) in walked:
            continue
        walked.add((identity.st_dev, identity.st_ino))
        for entry in entries:
            try:
                is_directory = entry.is_dir()  # through a link, as Git reads it
            except OSError:
                continue  # a link Git cannot resolve either, such as one to itself
            if is_directory:
                pending.append(Path(entry.path))
                continue
            if entry.is_file(follow_symlinks=False):
                continue  # the directory listing says so; no stat needed
            try:
                mode = entry.stat().st_mode  # through a link, as Git reads it
            except OSError:
                continue  # a broken link, which Git ignores
            if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
                raise RepositoryError(
                    f"'{entry.path}' is not a regular file (a named pipe or a device). Git "
                    "reads it, and would wait on it for ever or read it without end. "
                    "Remove it, or run Reveille on a fresh clone."
                )


def _git_dir_of(start: Path, *, search_up: bool) -> Path | None:
    """Return the Git directory Git would find from `start`, without running Git.

    Args:
        start: Where to look.
        search_up: Whether to look in its parents too.

    Returns:
        The `.git` directory, the directory a `.git` file names, `start` itself
        when it is bare, or None when none is found.

    Raises:
        RepositoryError: If a `.git` file is not a regular file.
    """
    for directory in [start, *start.parents] if search_up else [start]:
        dot_git = directory / ".git"
        if os.path.lexists(dot_git):
            if dot_git.is_dir():
                return dot_git
            if not _checked(dot_git):
                return None
            pointer = dot_git.read_text("utf-8", "replace").strip()
            if not pointer.startswith("gitdir:"):
                return None
            return directory / pointer.removeprefix("gitdir:").strip()
        if all((directory / name).exists() for name in ("HEAD", "objects", "refs")):
            return directory
    return None


def _checked(path: Path, *, bounded: bool = True) -> bool:
    """Return whether a file Git reads is there, refusing one that would block.

    Args:
        path: The file; a symbolic link is followed, as Git follows it.
        bounded: Whether a size past `_MAX_GIT_FILE_BYTES` is refused too.

    Returns:
        True for a regular file of a plausible size, False when it is absent.

    Raises:
        RepositoryError: If it is not a regular file, or is bounded and too large.
    """
    try:
        status = path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(status.st_mode):
        if stat.S_ISDIR(status.st_mode):
            return False
        raise RepositoryError(
            f"'{path}' is not a regular file (a named pipe or a device). Git reads it, "
            "and would wait on it for ever or read it without end. "
            "Remove it, or run Reveille on a fresh clone."
        )
    if bounded and status.st_size > _MAX_GIT_FILE_BYTES:
        raise RepositoryError(
            f"'{path}' is {status.st_size:,} bytes, larger than any configuration a person "
            f"writes (the limit is {_MAX_GIT_FILE_BYTES:,}). Reveille does not read it."
        )
    return True


def _check_includes(config: Path, depth: int) -> None:
    """Check every file a configuration file includes, conditionally or not.

    Args:
        config: A configuration file already checked.
        depth: How many includes led here.

    Raises:
        RepositoryError: If an included file is not a regular file, or is too large.
    """
    if depth >= _MAX_INCLUDE_DEPTH:
        return
    for value in _include_paths(config):
        if value.startswith("%(prefix)/"):
            # Git expands it to its install prefix, which Reveille cannot know for sure.
            raise RepositoryError(
                f"'{config}' includes '{value}', a path under Git's install prefix. "
                "Reveille checks every file a configuration includes before Git reads it, "
                "and cannot check this one."
            )
        target = Path(value).expanduser()
        if not target.is_absolute():
            target = config.parent / target
        if _checked(target):
            _check_includes(target, depth + 1)


def _include_paths(config: Path) -> list[str]:
    """Return the value of every `path` key in an `include` or `includeIf` section.

    Git reads the file, with includes off, so its own grammar decides what is a
    key (continuations, quoting, a byte-order mark), and nothing else is opened.
    Every condition is taken as true: a file that is listed is checked.

    Args:
        config: A configuration file already checked to be a regular file.

    Returns:
        The paths, as Git reads them.

    Raises:
        RepositoryError: If Git cannot read the file as configuration.
    """
    try:
        # Git reads the configuration of the repository it starts in, includes and all,
        # before `--file` applies: started inside this one, or with GIT_DIR naming it, it
        # would open the pipe this check exists to refuse. Every variable that names a
        # repository points at an empty directory instead.
        with tempfile.TemporaryDirectory() as nowhere:
            raw = _TimedGit(nowhere).execute(
                [
                    "git",
                    "config",
                    "--file",
                    str(config),
                    "--no-includes",
                    "-z",
                    "--get-regexp",
                    r"^include(if\..*)?\.path$",
                ],
                env=dict.fromkeys(_REPOSITORY_VARIABLES, nowhere),
            )
    except GitCommandError as exc:
        if exc.status == 1:  # no such key
            return []
        raise RepositoryError(
            f"Git cannot read '{config}' as configuration: {_git_error(exc)}"
        ) from exc
    entries = str(raw).split("\0")
    return [value for _, _, value in (e.partition("\n") for e in entries if e) if value]


def _absolute_git_dir(path: Path) -> str | None:
    """Return the Git directory Git finds from `path`, or None if it finds none."""
    try:
        return str(
            _TimedGit().execute(["git", "-C", str(path), "rev-parse", "--absolute-git-dir"])
        ).strip()
    except (GitCommandError, OSError):
        return None


def _git_error(exc: GitCommandError) -> str:
    """Return the first line Git wrote to stderr that is not a hint, or its exit status.

    Hints come first: Reveille's own `GIT_GRAFT_FILE` makes Git print one.
    """
    text = str(exc.stderr or "").strip().removeprefix("stderr: ").strip("'")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    said = [line for line in lines if not line.startswith("hint:")] or lines
    return said[0] if said else f"exit {exc.status}"


def _is_partial_clone(repo: Repo) -> bool:
    """Return whether a repository is a partial clone, from its own configuration.

    A promisor remote or `extensions.partialClone` means objects may be fetched
    on demand. Read by GitPython's parser, so no Git program runs.

    Args:
        repo: The repository.

    Returns:
        True when any remote is a promisor or the extension is set.
    """
    try:
        config = repo.config_reader("repository")
        for section in config.sections():
            if section.startswith("remote ") and config.get_value(section, "promisor", False):
                return True
        return bool(config.get_value("extensions", "partialclone", ""))
    except Exception:  # an unreadable config is reported by the first read instead
        return False


def _truncate(value: str, limit: int) -> str:
    """Bound an identity field's length, marking the cut.

    Args:
        value: The scrubbed field.
        limit: Maximum characters to keep.

    Returns:
        The value, or its first `limit` characters followed by an ellipsis.
    """
    if len(value) <= limit:
        return value
    return value[:limit] + _TRUNCATION_MARKER


def _empty_window(
    dated_after: int, dated_until: datetime.date | None, remedies: Sequence[str] = ()
) -> EmptyRepositoryError:
    """Explain an empty analysis window, naming commits dated after it.

    Args:
        dated_after: Commits left out for being dated after `dated_until`.
        dated_until: The date they were measured against, if any.
        remedies: What to try, one per filter that was given; none is suggested
            that the read did not apply.

    Returns:
        The error to raise.
    """
    if dated_after and dated_until is not None:
        dated = "1 commit is" if dated_after == 1 else f"{dated_after:,} commits are"
        return EmptyRepositoryError(
            f"No commits found within the analysis window: {dated} dated after "
            f"{dated_until.isoformat()}. Pass --until with a later date to include them."
        )
    if not remedies:
        return EmptyRepositoryError("No commits found within the specified analysis window.")
    tries = remedies[0] if len(remedies) == 1 else f"{', '.join(remedies[:-1])} or {remedies[-1]}"
    return EmptyRepositoryError(
        f"No commits found within the specified analysis window. Try {tries}."
    )


def _strip_control_chars(value: str) -> str:
    """Remove C0 control characters from a git identity field.

    Git leaves them in author fields, so a crafted name can carry the separators
    this reader splits on.

    Args:
        value: A raw author name or address straight from `git log`.

    Returns:
        The value with every C0 control character and DEL removed, and each byte
        that is not UTF-8 shown as U+FFFD, as a path's is.
    """
    return _shown(_CONTROL_CHARS_RE.sub("", value))


def _shown(value: str) -> str:
    """Show each byte Git gave that is not UTF-8 as U+FFFD, which every output can write.

    Args:
        value: Text decoded from Git's output, or a ref name.

    Returns:
        The value with each lone surrogate replaced.
    """
    return _UNDECODED_RE.sub("\ufffd", value)


def _strip_invisible(name: str) -> str:
    """Remove characters that make a name display as something it is not.

    Names only: rewriting an address, the identity key (ADR 0002), could merge people.

    Args:
        name: An author name, already scrubbed of control characters.

    Returns:
        The name without bidi controls, zero-width spaces or byte-order marks.
    """
    return _INVISIBLE_IN_NAMES_RE.sub("", name)


def _identity(
    raw_name: str, raw_email: str, mailmap: _Mailmap, exclude_set: set[str]
) -> tuple[str, str, set[str]]:
    """Resolve and scrub one commit's author, and match it against the exclusions.

    Args:
        raw_name: The author name as recorded.
        raw_email: The author address as recorded.
        mailmap: Parsed `.mailmap` lookup tables.
        exclude_set: Lowercased names and addresses to drop.

    Returns:
        The resolved name and address, and the exclusion values they match.
    """
    # Scrub before trusting: separators in a field can fabricate contributors.
    raw_name = _strip_control_chars(raw_name)
    raw_email = _strip_control_chars(raw_email)

    author_name, author_email = _resolve_identity(raw_name, raw_email, mailmap)
    # A `.mailmap` is as untrusted as an author field: same scrub.
    author_name = _strip_invisible(_strip_control_chars(author_name))
    author_email = _strip_control_chars(author_email)

    # Resolved and raw identity both match, so a value copied from `git log`
    # (which shows pre-mailmap names) still excludes the person. Matched before
    # the bounds below: a cut name is no longer the name an exclusion gives.
    hits = (
        exclude_set
        & {
            _match_key(author_name),
            _match_key(author_email),
            _match_key(raw_name),
            _match_key(raw_email),
        }
        if exclude_set
        else set()
    )
    author_name = _truncate(author_name, _MAX_NAME_LENGTH)
    author_email = _truncate(author_email, _MAX_EMAIL_LENGTH)
    # A name of only invisible characters is empty once cleaned; use the address.
    author_name = author_name or author_email
    return author_name, author_email, hits


def _parse_log_record(
    record: str,
    mailmap: _Mailmap,
    exclude_set: set[str],
    authentic_shas: Mapping[str, str],
    matched: set[str],
    undatable: set[str] | None = None,
    identities: dict[tuple[str, str], tuple[str, str, set[str]]] | None = None,
) -> Commit | None:
    """Turn one `git log` record into a Commit, or reject it.

    Every rejection is a defence: a crafted commit object can carry control
    characters in its author fields and a non-numeric timestamp.

    Args:
        record: One record from the split log output, without its separator.
        mailmap: Parsed `.mailmap` lookup tables.
        exclude_set: Lowercased names and addresses to drop.
        authentic_shas: Object names git reported for this revision whose record is
            the only well-formed one for that name (`_well_formed_shas`).
        matched: Mutated with every exclusion value that matched.
        undatable: Mutated with each commit whose timestamp no date can hold, so it
            is counted as unreadable rather than lost without a word.
        identities: Each author already resolved in this read, filled as it goes:
            the mailmap and the exclusions are fixed for the read, so one author
            is resolved once and its commits share the same strings.

    Returns:
        The parsed Commit, or None if empty, malformed, excluded or undatable.
    """
    if not record.strip():
        return None

    header, _, numstat_block = record.partition("\n")
    fields = header.split(_FIELD_SEP)
    if len(fields) != 5 or fields[0] != fields[4]:
        return None

    sha, raw_name, raw_email, committed_at, _ = fields

    # Shape alone can be forged; membership in the set git computed cannot.
    if not _SHA_RE.fullmatch(sha) or sha not in authentic_shas:
        return None

    resolved = None if identities is None else identities.get((raw_name, raw_email))
    if resolved is None:
        resolved = _identity(raw_name, raw_email, mailmap, exclude_set)
        if identities is not None:
            identities[(raw_name, raw_email)] = resolved
    author_name, author_email, hits = resolved
    if hits:
        matched |= hits
        return None

    try:
        timestamp = datetime.datetime.fromtimestamp(int(committed_at), tz=datetime.UTC)
    except (ValueError, OverflowError, OSError):
        # One unusable timestamp skips one record, not the report, and is counted.
        _logger.debug("skipping commit %s: unparseable timestamp", sha[:12])
        if undatable is not None:
            undatable.add(sha)
        return None

    lines_added, lines_deleted = _sum_numstat(numstat_block)
    return Commit(
        sha=authentic_shas[sha],  # a kept commit shares the string the rest of the read holds
        author_name=author_name,
        author_email=author_email,
        timestamp=timestamp,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )


def _selection(log_args: list[str]) -> list[str]:
    """Return the main read's arguments without its format and per-file output.

    Args:
        log_args: As `_build_log_args` gives them.

    Returns:
        The revision, window and path arguments alone, for a second read of the
        same commits.
    """
    return [a for a in log_args if a not in ("--numstat", "--name-status", _LOG_FORMAT)]


# Git reads a date only from 1970 through 2099 (Git 2.55, measured with
# `git rev-parse --since=`): past 2099 `--before` matched no commit and `--since`
# every one, and `@<seconds>` past it is read as another date. A bound outside
# those years is dropped where nothing Git can date lies beyond it, and moved to
# the nearest day Git reads where something could.
_GIT_FIRST_DAY = datetime.date(1970, 1, 1)
_GIT_LAST_DAY = datetime.date(2099, 12, 31)


def _git_after(day: datetime.date) -> str | None:
    """Return a lower date bound as Git reads it, or None when no dated commit is earlier."""
    if day <= _GIT_FIRST_DAY:
        return None
    return f"{min(day, _GIT_LAST_DAY).isoformat()}T00:00:00+00:00"


def _git_before(day: datetime.date) -> str | None:
    """Return an exclusive upper date bound as Git reads it, or None when none is later."""
    if day > _GIT_LAST_DAY:
        return None
    return f"{max(day, _GIT_FIRST_DAY).isoformat()}T00:00:00+00:00"


def _build_log_args(
    rev: str,
    since: datetime.date | None,
    until: datetime.date | None,
    supports_since_as_filter: bool = True,
    *,
    line_counts: bool = True,
    path: str | None = None,
    name_status: bool = False,
    exclude_paths: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """Build the argument lists for the numstat read and the SHA allowlist.

    Built together so both agree on revision and window; `rev-list` rejects
    `--numstat`, so neither is filtered from the other.

    Args:
        rev: The revision to walk, already checked not to begin with `-`.
        since: Inclusive start of the analysis window, if any.
        until: Inclusive end of the analysis window, if any.
        supports_since_as_filter: Whether git has `--since-as-filter`; else `--after`.
        line_counts: Whether to ask for per-file line counts (`--numstat`).
        path: Only commits changing this path, as a `:(literal)` pathspec.
        name_status: Ask for `--name-status` instead: paths without line counts.
        exclude_paths: Literal paths whose changes are left out; a commit that
            changed nothing else is left out with them.

    Returns:
        A `(log_args, rev_list_args)` pair.
    """
    files = ["--name-status"] if name_status else ["--numstat"] if line_counts else []
    log_args: list[str] = ["--no-merges", *files, _LOG_FORMAT]
    rev_list_args: list[str] = ["--no-merges"]

    # Boundaries are pinned to UTC: git reads a bare date in local time, so the
    # answer would depend on the machine (and `--deterministic` would not hold).
    after = None if since is None else _git_after(since)
    if after is not None:
        boundary = after
        # `--since` stops the walk at the first older commit, silently losing
        # in-window commits behind it on non-chronological history; the filter
        # does not. `--before` needs no equivalent: the walk starts newest.
        flag = "--since-as-filter" if supports_since_as_filter else "--after"
        log_args.append(f"{flag}={boundary}")
        rev_list_args.append(f"{flag}={boundary}")
    # One day past the boundary, so `--until` is inclusive of its own date.
    before = None if until is None else _git_before(until + datetime.timedelta(days=1))
    if before is not None:
        boundary = before
        log_args.append(f"--before={boundary}")
        rev_list_args.append(f"--before={boundary}")

    # `--end-of-options` stops option parsing; `--` separates revision from path.
    scoped = path is not None or bool(exclude_paths)
    for args in (log_args, rev_list_args):
        if scoped:
            # A pathspec turns on history simplification, which skips a merged
            # branch whose changes the merge did not keep (`-s ours`): commits
            # every other figure counts would vanish from this one.
            args.append("--full-history")
        args.extend(["--end-of-options", rev, "--"])
        if path is not None:
            args.append(f":(literal){path}")
        # With no other pathspec, Git subtracts an exclusion from the whole tree.
        args.extend(f":(top,exclude,literal){excluded}" for excluded in exclude_paths)

    return log_args, rev_list_args


def _match_key(value: str) -> str:
    """Return the form an exclusion is compared in.

    NFC, invisible format characters (Unicode category Cf) removed, spaces
    collapsed, lower case. A trailing or doubled space, a decomposed accent, or a
    word joiner a crafted name carries must not let an excluded person back in:
    for a privacy flag, matching too little is the wrong way round. Only the
    comparison changes; names are shown and counted unchanged.
    """
    return _bounded_match_key(value[:_MAX_MATCH_LENGTH])


@functools.lru_cache(maxsize=2048)
def _bounded_match_key(value: str) -> str:
    """Compute `_match_key` for a value already cut to its bound; called only by it.

    A history names each person on many commits, so each is computed once.
    """
    visible = "".join(
        c for c in unicodedata.normalize("NFC", value) if unicodedata.category(c) != "Cf"
    )
    return " ".join(visible.split()).lower()


def _exclusion_requests(exclude_authors: list[str], mailmap: _Mailmap) -> dict[str, set[str]]:
    """Map each exclusion value to every form it reaches.

    `--exclude-author` removes a person, who may have several identities; for a
    privacy flag, erring towards removing too little is the wrong way round. A
    GitHub noreply address reaches its account in either form (ADR 0023), and a
    `.mailmap` entry reaches its canonical name and address.

    Args:
        exclude_authors: Raw values as supplied, by name or by address.
        mailmap: The parsed `.mailmap` for this repository.

    Returns:
        Each value's match key, mapped to that key and every form it expands to.
    """
    requests: dict[str, set[str]] = {}
    for value in exclude_authors:
        key = _match_key(value)
        forms = requests.setdefault(key, set())
        forms |= {key, _match_key(_normalise_github_noreply(key, mailmap))}
        for entry in list(forms):
            canonical = mailmap.by_email.get(entry)
            if canonical is not None:
                canonical_name, canonical_email = canonical
                if canonical_name:
                    forms.add(_match_key(canonical_name))
                forms.add(_match_key(canonical_email))

            # Four-field form: a value naming either half expands to the entry.
            for (commit_name, commit_email), (name, email) in mailmap.by_name_and_email.items():
                if entry in (_match_key(commit_name), _match_key(commit_email)):
                    if name:
                        forms.add(_match_key(name))
                    forms.add(_match_key(email))
    return requests
