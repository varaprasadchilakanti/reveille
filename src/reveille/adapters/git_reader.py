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

import datetime
import logging
import os
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
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
from reveille.domain.state import RepositoryState, Worktree, quiet_branches
from reveille.exceptions import EmptyRepositoryError, RepositoryError

# Separators for the `git log` read: 0x1E and 0x1F are rare, not impossible.
# Git does not strip them from author fields, so a crafted commit can split a
# record; every field is scrubbed after parsing (_strip_control_chars).
_logger = logging.getLogger(__name__)

_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"

_LOG_FORMAT = f"--format={_RECORD_SEP}%H{_FIELD_SEP}%an{_FIELD_SEP}%ae{_FIELD_SEP}%ct"

# A well-formed record opens with a 40-character object name.
_SHA_RE = re.compile(r"[0-9a-f]{40}")

# C0 controls and DEL, tab and newlines included: they break downstream formats.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# Bidi overrides, embeddings and isolates, zero-width space and BOM: they change
# how a name displays. ZWJ, ZWNJ, LRM and RLM are kept; real names use them.
_INVISIBLE_IN_NAMES_RE = re.compile("[\u202a-\u202e\u2066-\u2069\u200b\ufeff]")

# Caps on attacker-controlled identity fields, which the report repeats many
# times. 320 is the RFC 5321 address maximum; truncation is visibly marked.
_MAX_NAME_LENGTH = 256
_MAX_EMAIL_LENGTH = 320
_TRUNCATION_MARKER = "\u2026"

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


def _parse_mailmap_line(line: str) -> tuple[str, ...] | None:
    """Parse one `.mailmap` line in a single linear pass, as Git does.

    Returns the fields of one of gitmailmap(5)'s four forms. A name ends at the
    first `<` and must be followed by whitespace before it. Not a regex: lazy
    patterns backtracked quadratically on hostile lines.

    Args:
        line: The line, comment removed and stripped.

    Returns:
        The fields, or None for a malformed line.
    """
    fields: list[tuple[str, str]] = []
    position = 0
    while (left := line.find("<", position)) >= 0:
        right = line.find(">", left + 1)
        if right <= left + 1 or len(fields) == 2:
            return None
        before = line[position:left]
        if fields and not before[:1].isspace():
            return None
        if before.strip() and not before[-1].isspace():
            return None
        fields.append((before.strip(), line[left + 1 : right]))
        position = right + 1
    if line[position:].strip():
        return None
    match fields:
        case [(name, email)] if name:
            return (name, email)
        case [("", proper), ("", commit)]:
            return (proper, commit)
        case [(name, proper), ("", commit)] if name:
            return (name, proper, commit)
        case [(name, proper), (commit_name, commit)] if name and commit_name:
            return (name, proper, commit_name, commit)
    return None


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
    for _path, line_added, line_deleted in _iter_numstat(block):
        added += line_added
        deleted += line_deleted
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


def _parse_worktrees(output: str) -> list[Worktree]:
    """Parse `git worktree list --porcelain`: blank-line separated records.

    Args:
        output: Git's output.

    Returns:
        The worktrees, the main one first.
    """
    found: list[Worktree] = []
    for record in output.strip().split("\n\n"):
        values: dict[str, str] = {}
        for line in record.splitlines():
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

    Undecoded, a non-ASCII path became a spurious hotspot and area.

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
        return url
    rest = rest.split("#", 1)[0].split("?", 1)[0]
    authority, slash, path = rest.partition("/")
    userinfo, at, host = authority.rpartition("@")
    if at:
        if scheme.rpartition("::")[2].lower() in ("http", "https"):
            authority = host
        else:
            authority = f"{userinfo.partition(':')[0]}@{host}"
    return f"{scheme}://{authority}{slash}{path}"


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
        self._file_stats: tuple[FileStats, ...] = ()
        #: Commits the last `read_commits` dropped as dated after `dated_until`.
        self.commits_dated_after: int = 0
        #: Commits whose log record could not be read; counted nowhere, stated (ADR 0019).
        self.commits_unreadable: int = 0
        #: Who changed each directory, when `read_commits` got an `area_depth`.
        self.area_activity: tuple[AreaActivity, ...] = ()
        #: Files added in the last `read_commits` with `name_status`.
        self.files_added: int = 0
        self.unmatched_exclusions: tuple[str, ...] = ()
        try:
            self._repo = Repo(str(repo_path), search_parent_directories=False)
        except InvalidGitRepositoryError as exc:
            # An unreadable `.git` raises the same exception as a missing one;
            # the fixes differ, so tell them apart.
            git_dir = repo_path / ".git"
            if git_dir.exists() and not os.access(git_dir, os.R_OK | os.X_OK):
                raise RepositoryError(
                    f"'{repo_path}' is a Git repository, but its .git directory "
                    "cannot be read. Check the permissions on it."
                ) from exc
            raise RepositoryError(
                f"'{repo_path}' is not a valid Git repository. "
                "Give the root of a working tree or a bare repository."
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
        )
        if _is_partial_clone(self._repo):
            raise RepositoryError(
                f"'{repo_path}' is a partial clone (made with --filter): some of its "
                "objects are still on the server, and reading them would make Git "
                "fetch them. Reveille makes no network call and changes no Git data, "
                "so it does not read a partial clone. Run it on a full clone."
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

        Returns:
            Commits sorted most recent first.

        Raises:
            RepositoryError: If the branch does not exist.
            EmptyRepositoryError: If no commits remain after filtering.
        """
        # Cleared at entry so a call that raises leaves no stale result.
        self.unmatched_exclusions = ()

        rev = branch or self._resolve_active_branch()

        # A leading `-` makes git read the revision as an option (`--output=...`
        # overwrites a file), and `branch` can come from an untrusted reveille.toml.
        if rev.startswith("-"):
            raise RepositoryError(
                f"Refusing to use {rev!r} as a revision: a value beginning with "
                "'-' is interpreted by git as a command-line option rather than "
                "a branch. If a ref really has this name, rename it."
            )

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
        )

        # Read first: an exclusion names a person, expanded through the mailmap.
        mailmap = self._read_mailmap()
        self._mailmap_applied = bool(mailmap.by_email or mailmap.by_name_and_email)
        accounts, usernames = self._noreply_accounts(rev)
        mailmap = replace(mailmap, noreply_accounts=accounts, noreply_usernames=usernames)

        exclude_set = _expand_exclusions(exclude_authors, mailmap)

        # An unborn HEAD is a negative answer, not a read failure.
        if not self._repo.head.is_valid():
            raise EmptyRepositoryError(
                f"Repository at '{self._repo_path}' contains no commits. "
                "Make at least one commit before generating a report."
            )

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
            authentic_shas = set(authentic_order)
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to enumerate commits on branch '{rev}'. "
                "Verify the branch exists in this repository."
            ) from exc

        _logger.debug("git log %s", " ".join(log_args))
        try:
            raw_log = self._git().log(*log_args)
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to read commits from branch '{rev}'. "
                f"Verify the branch name is correct. Detail: {exc}"
            ) from exc

        # An identity is its address (ADR 0002): excluding one name drops every
        # commit under the addresses it reaches.
        records = raw_log.split(_RECORD_SEP)
        requested = set(exclude_set)
        reached = self._addresses_in_history(rev, mailmap, exclude_set)
        exclude_set |= {address for addresses in reached.values() for address in addresses}
        _state_wide_exclusions(reached)

        commits: list[Commit] = []
        matched: set[str] = set()
        # Accumulated while streaming: memory is bounded by distinct paths.
        file_totals: dict[str, list[int]] = {}
        area_totals: dict[str, _AreaTotal] = {}
        added_paths: set[str] = set()
        dated_after = 0
        for record in records:
            commit = _parse_log_record(record, mailmap, exclude_set, authentic_shas, matched)
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
        self.commits_unreadable = _unreadable(records, authentic_shas)
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
            log_args, authentic_order, commits, mailmap, exclude_set, matched
        )

        # A filter that matched nothing is almost always a typo; say so.
        # Assigned unconditionally so a reused reader never reports stale values.
        unmatched = sorted(requested - matched - set(reached))
        self.unmatched_exclusions = tuple(unmatched)
        if unmatched:
            _logger.warning("--exclude-author matched no commits for: %s", ", ".join(unmatched))

        if not commits:
            raise _empty_window(dated_after, dated_until)

        _logger.debug(
            "read %d commits from %s (%d bytes of git log output)",
            len(commits),
            rev,
            len(raw_log),
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
            analysed_branch=branch or self._resolve_active_branch(),
            total_commits=total_commits,
            unique_contributors=unique_contributors,
            analysis_since=analysis_since,
            analysis_until=analysis_until,
            generated_at=datetime.datetime.now(tz=datetime.UTC),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_active_branch(self) -> str:
        """Return the active branch name, or 'HEAD' when detached.

        Returns:
            The branch name, or 'HEAD'.
        """
        try:
            return self._repo.active_branch.name
        except TypeError:
            return "HEAD"

    def _credit_co_authors(
        self,
        log_args: list[str],
        authentic_order: list[str],
        commits: list[Commit],
        mailmap: _Mailmap,
        exclude_set: set[str],
        matched: set[str],
    ) -> list[Commit]:
        """Attach the identities each commit's `Co-authored-by` trailers credit.

        A second NUL-separated `git log` over the same selection (ADR 0014).
        Records must line up one for one with `rev-list`, or a crafted trailer
        could forge another commit's record; otherwise nobody is credited.

        Args:
            log_args: The main read's arguments, whose selection is reused.
            authentic_order: Hashes from `rev-list`, in log order.
            commits: The commits being counted.
            mailmap: Parsed `.mailmap`, applied as for authors.
            exclude_set: Lowercased exclusions; a matching co-author is dropped.
            matched: Mutated with every exclusion value that matched.

        Returns:
            The commits, with `co_authors` set where any are credited.
        """
        if not commits:
            return commits
        selection = [a for a in log_args if a not in ("--numstat", "--name-status", _LOG_FORMAT)]
        try:
            raw = self._trailer_log(selection)
        except GitCommandError as exc:
            _logger.warning("co-author trailers could not be read: %s", exc)
            return commits
        records = [r for r in raw.split("\0") if r.strip()]
        hashes = [r.split(_FIELD_SEP, 1)[0].strip() for r in records]
        if hashes != authentic_order:
            _logger.warning(
                "co-author trailers did not line up with the commits read; "
                "no co-author is credited in this report"
            )
            return commits

        credited: dict[str, tuple[tuple[str, str], ...]] = {}
        authors = {c.sha: c.author_email.lower() for c in commits}
        for record in records:
            sha, _, values = record.partition(_FIELD_SEP)
            sha = sha.strip()
            if sha not in authors or not values.strip():
                continue
            found = _co_author_identities(values, mailmap, exclude_set, matched, authors[sha])
            if found:
                credited[sha] = found
        return [replace(c, co_authors=credited[c.sha]) if c.sha in credited else c for c in commits]

    def _git(self) -> Any:
        """Return the Git command runner, with settings that change what is read pinned.

        `log.follow` would desynchronise `log` from `rev-list`, so results must
        not depend on the user's configuration.

        Returns:
            GitPython's command runner for this repository.
        """
        # Pinned off: a repository's config could make Git run gpg.program or an
        # fsmonitor program (ADR 0024).
        return self._repo.git(
            c=[
                "log.follow=false",
                "log.showSignature=false",
                "core.fsmonitor=false",
                "status.submoduleSummary=false",
            ]
        )

    def _trailer_log(self, selection: list[str]) -> str:
        """Run the co-author read: NUL-separated hashes and trailer values.

        Args:
            selection: The main read's arguments without format and line counts.

        Returns:
            Git's output.
        """
        return str(self._git().log("-z", _TRAILER_FORMAT, *selection))

    def _noreply_accounts(self, rev: str) -> tuple[dict[str, str], dict[str, str]]:
        """Read which GitHub accounts committed, for folding noreply addresses (ADR 0023).

        One pass over author addresses on the branch, newest first, so the first
        username seen for an account number is its current one.

        Args:
            rev: The analysed branch, already checked not to begin with `-`.

        Returns:
            Account number to canonical address, and legacy username to that address
            for usernames only one account used.
        """
        try:
            out = str(self._git().log("--no-merges", "--format=%aE", "--end-of-options", rev, "--"))
        except GitCommandError:
            return {}, {}
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
        """Read the repository's present state, changing nothing (ADR 0024).

        Every call runs with optional locks off and fsmonitor pinned off (`_git`), so
        `git status` neither rewrites the index nor runs a program the repository names.

        Returns:
            The branch, work in progress, working tree, stashes, worktrees, branch
            counts and latest tag.
        """
        status = _Status()
        if not self._repo.bare:
            raw = str(
                self._git().status(
                    "--porcelain=v2",
                    "--branch",
                    "-z",
                    "--untracked-files=normal",
                    "--ignore-submodules=all",
                )
            )
            status = _parse_status(raw)
        else:
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
        )

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
        """List the working trees attached to this repository."""
        try:
            return _parse_worktrees(str(self._git().worktree("list", "--porcelain")))
        except GitCommandError:
            return []

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

    def _latest_tag(self, head: str | None) -> tuple[str | None, int | None]:
        """Return the nearest reachable tag and the non-merge commits after it."""
        if head is None:
            return None, None
        try:
            tag = str(
                self._git().describe("--tags", "--abbrev=0", "--end-of-options", head)
            ).strip()
            count = str(
                self._git().rev_list("--no-merges", "--count", f"{tag}..{head}", "--")
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
            RepositoryError: If it begins with `-` (git would read an option) or
                names no commit here.
        """
        if not revision or revision.startswith("-"):
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
        """
        rev = branch or self._resolve_active_branch()
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

    def last_change_before(
        self,
        area: str,
        branch: str | None,
        before_commit: str | None,
        before_date: datetime.date | None,
    ) -> datetime.date | None:
        """Return when a directory last changed before a point, or None.

        Exclusions do not apply: this is about the directory, not a person.

        Args:
            area: A directory path; the root area is not looked up.
            branch: The analysed branch; the active branch if None.
            before_commit: Look at this commit's history (inclusive).
            before_date: Or look at the branch's history before this date.

        Returns:
            The date (UTC) of the latest non-merge commit that changed it, if any.
        """
        if area == ROOT_AREA:
            return None
        args = ["-1", "--no-merges", "--format=%ct"]
        if before_commit is not None:
            args += ["--end-of-options", before_commit]
        else:
            rev = branch or self._resolve_active_branch()
            if before_date is not None:
                args.append(f"--before={before_date.isoformat()}T00:00:00+00:00")
            args += ["--end-of-options", rev]
        try:
            out = str(self._git().log(*args, "--", f":(literal){area}")).strip()
        except GitCommandError:
            return None
        if not out.isdigit():
            return None
        return datetime.datetime.fromtimestamp(int(out), tz=datetime.UTC).date()

    def resolve_head_sha(self, branch: str | None = None) -> str | None:
        """Return the full SHA at the tip of the analysed ref, pinning the report.

        Args:
            branch: The ref to resolve; the active branch if None.

        Returns:
            The 40-character SHA, or None if the ref cannot be resolved.
        """
        rev = branch or self._resolve_active_branch()
        try:
            return str(self._repo.commit(rev).hexsha)
        except Exception:
            return None

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
        """
        reached: dict[str, set[str]] = {}
        if not exclude_set:
            return reached
        try:
            raw = str(self._git().log("-z", "--format=%an%x1f%ae", "--end-of-options", rev, "--"))
        except GitCommandError:
            return reached
        for record in raw.split("\0"):
            fields = record.split(_FIELD_SEP)
            if len(fields) != 2:
                continue
            _, address, hits = _identity(fields[0], fields[1], mailmap, exclude_set)
            for value in hits:
                reached.setdefault(value, set()).add(address.lower())
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
            True when Git reports a shallow repository; False otherwise or on error.
        """
        try:
            return str(self._repo.git.rev_parse("--is-shallow-repository")).strip() == "true"
        except Exception:
            return False

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

    def _supports_since_as_filter(self) -> bool:
        """Whether the installed git (2.37 or newer) understands `--since-as-filter`.

        Probed: older git falls back, possibly under-reporting non-linear history.

        Returns:
            True when git is 2.37 or newer.
        """
        try:
            raw = str(self._repo.git.version())
        except Exception:
            return False
        match = re.search(r"(\d+)\.(\d+)", raw)
        if not match:
            return False
        return (int(match.group(1)), int(match.group(2))) >= (2, 37)

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
        except OSError:
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
            # A comment runs to end of line.
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue

            fields = _parse_mailmap_line(stripped)
            if fields is None:
                continue
            if len(fields) == 4:
                mailmap.by_name_and_email[(fields[2].strip().lower(), fields[3].lower())] = (
                    fields[0],
                    fields[1].lower(),
                )
            elif len(fields) == 3:
                mailmap.by_email[fields[2].lower()] = (fields[0], fields[1].lower())
            elif stripped.startswith("<"):
                # Email-only form: None keeps the commit's name.
                mailmap.by_email[fields[1].lower()] = (None, fields[0].lower())
            else:
                email = fields[1].lower()
                mailmap.by_email[email] = (fields[0], email)

        return mailmap


#: Hash, then each `Co-authored-by` value, unfolded; used with `-z`.
_TRAILER_FORMAT = (
    f"--format=%H{_FIELD_SEP}"
    f"%(trailers:key=Co-authored-by,valueonly,unfold,separator=%x{ord(_FIELD_SEP):02x})"
)

#: Distinct co-authors kept per commit, bounding hostile messages.
_MAX_CO_AUTHORS = 32

_CO_AUTHOR_RE = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]+)>\s*$")


def _co_author_identities(
    values: str,
    mailmap: _Mailmap,
    exclude_set: set[str],
    matched: set[str],
    author: str,
) -> tuple[tuple[str, str], ...]:
    """Resolve one commit's `Co-authored-by` values like author identities.

    Args:
        values: The trailer values, separated by the field separator.
        mailmap: Parsed `.mailmap`.
        exclude_set: Lowercased exclusions.
        matched: Mutated with every exclusion value that matched.
        author: The commit's own author address, lowercased.

    Returns:
        Up to `_MAX_CO_AUTHORS` distinct `(name, address)` pairs.
    """
    found: dict[str, str] = {}
    dropped = 0
    for value in values.split(_FIELD_SEP):
        parsed = _CO_AUTHOR_RE.match(_strip_control_chars(value.strip()))
        if parsed is None:
            continue
        raw_name = _truncate(parsed.group("name").strip(), _MAX_NAME_LENGTH)
        raw_email = _truncate(parsed.group("email").strip(), _MAX_EMAIL_LENGTH)
        name, email = _resolve_identity(raw_name, raw_email, mailmap)
        name = _truncate(_strip_invisible(_strip_control_chars(name)), _MAX_NAME_LENGTH)
        email = _truncate(_strip_control_chars(email), _MAX_EMAIL_LENGTH).lower()
        hits = exclude_set & {name.lower(), email, raw_name.lower(), raw_email.lower()}
        if hits:
            matched.update(hits)
            continue
        if email == author or email in found:
            continue
        if len(found) == _MAX_CO_AUTHORS:
            dropped += 1
            continue
        found[email] = name or email
    if dropped:
        _logger.warning(
            "a commit names more than %d co-authors; %d ignored", _MAX_CO_AUTHORS, dropped
        )
    return tuple((name, email) for email, name in found.items())


def _count_commits(n: int) -> str:
    """Return "1 commit" or "N commits"."""
    return f"{n:,} commit" if n == 1 else f"{n:,} commits"


def _unreadable(records: list[str], authentic_shas: set[str]) -> int:
    """Count the commits whose record could not be read, and say so (ADR 0019).

    Args:
        records: The main read's records.
        authentic_shas: Object names git reported for this revision.

    Returns:
        How many authentic commits had no well-formed record.
    """
    unreadable = len(authentic_shas - _well_formed_shas(records, authentic_shas))
    if unreadable:
        _logger.warning(
            "%s could not be read and %s not counted: an author field held "
            "characters the read splits on.",
            _count_commits(unreadable),
            "is" if unreadable == 1 else "are",
        )
    return unreadable


def _well_formed_shas(records: list[str], authentic_shas: set[str]) -> set[str]:
    """Return the object names whose log record has the expected shape.

    A record split by injected separators fails this check, so its commit is
    counted as unreadable rather than lost silently (ADR 0019).

    Args:
        records: The main read's records.
        authentic_shas: Object names git reported for this revision.

    Returns:
        The names of commits whose record has four fields and an authentic name.
    """
    shas: set[str] = set()
    for record in records:
        fields = record.partition("\n")[0].split(_FIELD_SEP)
        if len(fields) == 4 and fields[0] in authentic_shas:
            shas.add(fields[0])
    return shas


def _state_wide_exclusions(reached: dict[str, set[str]]) -> None:
    """Warn when a name reached more than one address (ADR 0020).

    A shared name removes both people: safe for privacy, but not silent.

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


def _empty_window(dated_after: int, dated_until: datetime.date | None) -> EmptyRepositoryError:
    """Explain an empty analysis window, naming commits dated after it.

    Args:
        dated_after: Commits left out for being dated after `dated_until`.
        dated_until: The date they were measured against, if any.

    Returns:
        The error to raise.
    """
    if dated_after and dated_until is not None:
        dated = "1 commit is" if dated_after == 1 else f"{dated_after:,} commits are"
        return EmptyRepositoryError(
            f"No commits found within the analysis window: {dated} dated after "
            f"{dated_until.isoformat()}. Pass --until with a later date to include them."
        )
    return EmptyRepositoryError(
        "No commits found within the specified analysis window. "
        "Try widening the date range or removing author filters."
    )


def _strip_control_chars(value: str) -> str:
    """Remove C0 control characters from a git identity field.

    Git leaves them in author fields, so a crafted name can carry the separators
    this reader splits on.

    Args:
        value: A raw author name or address straight from `git log`.

    Returns:
        The value with every C0 control character and DEL removed.
    """
    return _CONTROL_CHARS_RE.sub("", value)


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
    raw_name = _truncate(_strip_control_chars(raw_name), _MAX_NAME_LENGTH)
    raw_email = _truncate(_strip_control_chars(raw_email), _MAX_EMAIL_LENGTH)

    author_name, author_email = _resolve_identity(raw_name, raw_email, mailmap)
    # A `.mailmap` is as untrusted as an author field: same scrub and bounds.
    author_name = _truncate(_strip_invisible(_strip_control_chars(author_name)), _MAX_NAME_LENGTH)
    author_email = _truncate(_strip_control_chars(author_email), _MAX_EMAIL_LENGTH)
    # A name of only invisible characters is empty once cleaned; use the address.
    author_name = author_name or author_email

    # Resolved and raw identity both match, so a value copied from `git log`
    # (which shows pre-mailmap names) still excludes the person.
    hits = exclude_set & {
        author_name.lower(),
        author_email.lower(),
        raw_name.lower(),
        raw_email.lower(),
    }
    return author_name, author_email, hits


def _parse_log_record(
    record: str,
    mailmap: _Mailmap,
    exclude_set: set[str],
    authentic_shas: set[str],
    matched: set[str],
) -> Commit | None:
    """Turn one `git log` record into a Commit, or reject it.

    Every rejection is a defence: a crafted commit object can carry control
    characters in its author fields and a non-numeric timestamp.

    Args:
        record: One record from the split log output, without its separator.
        mailmap: Parsed `.mailmap` lookup tables.
        exclude_set: Lowercased names and addresses to drop.
        authentic_shas: Object names git itself reported for this revision.
        matched: Mutated with every exclusion value that matched.

    Returns:
        The parsed Commit, or None if empty, malformed, excluded or undatable.
    """
    if not record.strip():
        return None

    header, _, numstat_block = record.partition("\n")
    fields = header.split(_FIELD_SEP)
    if len(fields) != 4:
        return None

    sha, raw_name, raw_email, committed_at = fields

    # Shape alone can be forged; membership in the set git computed cannot.
    if not _SHA_RE.fullmatch(sha) or sha not in authentic_shas:
        return None

    author_name, author_email, hits = _identity(raw_name, raw_email, mailmap, exclude_set)
    if hits:
        matched |= hits
        return None

    try:
        timestamp = datetime.datetime.fromtimestamp(int(committed_at), tz=datetime.UTC)
    except (ValueError, OverflowError, OSError):
        # One unusable timestamp skips one record, not the report.
        _logger.debug("skipping commit %s: unparseable timestamp", sha[:12])
        return None

    lines_added, lines_deleted = _sum_numstat(numstat_block)
    return Commit(
        sha=sha,
        author_name=author_name,
        author_email=author_email,
        timestamp=timestamp,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )


def _build_log_args(
    rev: str,
    since: datetime.date | None,
    until: datetime.date | None,
    supports_since_as_filter: bool = True,
    *,
    line_counts: bool = True,
    path: str | None = None,
    name_status: bool = False,
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

    Returns:
        A `(log_args, rev_list_args)` pair.
    """
    files = ["--name-status"] if name_status else ["--numstat"] if line_counts else []
    log_args: list[str] = ["--no-merges", *files, _LOG_FORMAT]
    rev_list_args: list[str] = ["--no-merges"]

    # Boundaries are pinned to UTC: git reads a bare date in local time, so the
    # answer would depend on the machine (and `--deterministic` would not hold).
    if since is not None:
        boundary = f"{since.isoformat()}T00:00:00+00:00"
        # `--since` stops the walk at the first older commit, silently losing
        # in-window commits behind it on non-chronological history; the filter
        # does not. `--before` needs no equivalent: the walk starts newest.
        flag = "--since-as-filter" if supports_since_as_filter else "--after"
        log_args.append(f"{flag}={boundary}")
        rev_list_args.append(f"{flag}={boundary}")
    if until is not None:
        # One day past the boundary, so `--until` is inclusive of its own date.
        inclusive_until = (until + datetime.timedelta(days=1)).isoformat()
        boundary = f"{inclusive_until}T00:00:00+00:00"
        log_args.append(f"--before={boundary}")
        rev_list_args.append(f"--before={boundary}")

    # `--end-of-options` stops option parsing; `--` separates revision from path.
    for args in (log_args, rev_list_args):
        args.extend(["--end-of-options", rev, "--"])
        if path is not None:
            args.append(f":(literal){path}")

    return log_args, rev_list_args


def _expand_exclusions(exclude_authors: list[str], mailmap: _Mailmap) -> set[str]:
    """Expand each exclusion to every identity the `.mailmap` ties it to.

    `--exclude-author` removes a person, who may have several identities; for a
    privacy flag, erring towards removing too little is the wrong way round.

    Args:
        exclude_authors: Raw values as supplied, by name or by address.
        mailmap: The parsed `.mailmap` for this repository.

    Returns:
        A lowercased set of the values plus any canonical names and addresses.
    """
    expanded = {entry.lower() for entry in exclude_authors}

    for entry in list(expanded):
        canonical = mailmap.by_email.get(entry)
        if canonical is not None:
            canonical_name, canonical_email = canonical
            if canonical_name:
                expanded.add(canonical_name.lower())
            expanded.add(canonical_email.lower())

        # Four-field form: a value naming either half expands to the entry.
        for (commit_name, commit_email), (name, email) in mailmap.by_name_and_email.items():
            if entry in (commit_name, commit_email):
                if name:
                    expanded.add(name.lower())
                expanded.add(email.lower())

    return expanded
