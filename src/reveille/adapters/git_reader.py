# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Git repository reader adapter.

Translates raw GitPython data into typed domain models. This is the
only layer in Reveille that imports GitPython. All other layers
receive domain objects and have no knowledge of the underlying library.

Identity resolution uses author email as the canonical contributor key.
Author name is taken from the contributor's most recent commit, which
handles name changes over a repository's lifetime gracefully. A `.mailmap`
is applied first where present, then GitHub's two private-commit address
forms are folded together so one account does not split across both.

Merge commits are excluded from all analysis. They inflate line counts
and commit volumes without reflecting individual contributor activity.

Commit history is read in a single `git log --numstat` subprocess.
Reading per-commit line counts through GitPython's ``Commit.stats``
instead spawns one `git diff` per commit, which dominates runtime on
any repository large enough to care about.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import GitCommandError

from reveille.domain.models import Commit, ContributorStats, RepositoryMetadata
from reveille.exceptions import EmptyRepositoryError, RepositoryError

# Record and field delimiters for the single-pass `git log` read.
# ASCII 0x1E (record separator) and 0x1F (unit separator) are chosen because
# they are vanishingly rare in real commit metadata, not because they are
# impossible there. Git's ident sanitiser strips `<`, `>` and newlines from an
# author field, but it does NOT strip other C0 control characters, so a commit
# object written directly with `git hash-object --literally` can embed these
# separators in an author name or address and split one record into several.
# Every field is therefore scrubbed after parsing -- see _strip_control_chars.
_logger = logging.getLogger(__name__)

_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"

_LOG_FORMAT = f"--format={_RECORD_SEP}%H{_FIELD_SEP}%an{_FIELD_SEP}%ae{_FIELD_SEP}%ct"

# A well-formed record always opens with a 40-character object name. Checking it
# is a cheap way to discard a record that separator injection has split.
_SHA_RE = re.compile(r"[0-9a-f]{40}")

# C0 controls and DEL. Tab, newline and carriage return are included: none of
# them belongs in an author name, and all three break downstream formats.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# Upper bounds on an identity field. Git imposes none, and the field is
# attacker-controlled in the threat model this reader is written against: a
# repository somebody else authored. Measured before capping, a single commit
# with a 100,000-character author name turned a four-commit repository into a
# 6.5 MB report, because the name is repeated in the table, two bar charts,
# every tooltip, the heatmap contributor list, and the JSON and CSV. A
# 1,000,000-character name reached 1.5 GB of resident memory.
#
# 256 is far past any real display name; 320 is the RFC 5321 maximum for an
# address. Truncation is marked so a reader can see it happened rather than
# wondering why a name looks wrong.
_MAX_NAME_LENGTH = 256
_MAX_EMAIL_LENGTH = 320
_TRUNCATION_MARKER = "\u2026"

# GitHub's prefixed private-commit address: 12345678+username@users.noreply.github.com.
# The username is captured; the numeric account ID is discarded.
_GITHUB_NOREPLY_RE = re.compile(
    r"^\d+\+(?P<username>[^@]+)@users\.noreply\.github\.com$",
    re.IGNORECASE,
)

# The four .mailmap forms documented in gitmailmap(5). Ordered most
# specific first: a four-field line also satisfies no other pattern, but
# an email-only line would otherwise be captured by the name-only form
# with the literal "<proper@email>" text taken as a display name.
_MAILMAP_FOUR_FIELD = re.compile(r"^(.+?)\s+<([^>]+)>\s+(.+?)\s+<([^>]+)>$")
_MAILMAP_THREE_FIELD = re.compile(r"^(.+?)\s+<([^>]+)>\s+<([^>]+)>$")
_MAILMAP_EMAIL_ONLY = re.compile(r"^<([^>]+)>\s+<([^>]+)>$")
_MAILMAP_NAME_ONLY = re.compile(r"^(.+?)\s+<([^>]+)>$")


def _normalise_github_noreply(email: str) -> str:
    """Strip the numeric account prefix from a GitHub noreply address.

    GitHub issues two forms of private commit address for the same account:
    the legacy `username@users.noreply.github.com` and, since 2017, the
    prefixed `12345678+username@users.noreply.github.com`. A contributor
    whose account spans the change appears under both, and the numeric ID
    also leaks into report output for no reader benefit.

    Args:
        email: An author email address, in any form.

    Returns:
        The address with the numeric prefix removed if it is a prefixed
        GitHub noreply address, otherwise the address unchanged.
    """
    match = _GITHUB_NOREPLY_RE.match(email)
    if match is None:
        return email
    return f"{match.group('username')}@users.noreply.github.com"


@dataclass(frozen=True)
class _Mailmap:
    """Parsed `.mailmap` lookup tables.

    Git matches a commit against the most specific entry available, so
    the two forms that carry a commit name are kept apart from those
    keyed on email alone.

    Attributes:
        by_email: Keyed on lowercased commit email. Covers the name-only,
            email-only, and three-field forms. A `None` canonical name
            means the entry replaces the email only and the commit's own
            name is kept, which is the email-only form's semantics.
        by_name_and_email: Keyed on (lowercased commit name, lowercased
            commit email). Covers the four-field form, which matches only
            when both fields agree.
    """

    by_email: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    by_name_and_email: dict[tuple[str, str], tuple[str | None, str]] = field(default_factory=dict)

    def lookup(self, name: str, email: str) -> tuple[str | None, str] | None:
        """Find the most specific entry matching a commit identity.

        Both names and emails are matched case-insensitively, as Git does.

        Args:
            name: Author name as recorded on the commit.
            email: Author email as recorded on the commit.

        Returns:
            The matching (canonical_name, canonical_email) entry, or None
            when no entry applies.
        """
        entry = self.by_name_and_email.get((name.lower(), email.lower()))
        if entry is not None:
            return entry
        return self.by_email.get(email.lower())


def _resolve_identity(name: str, email: str, mailmap: _Mailmap) -> tuple[str, str]:
    """Resolve a raw author identity to its canonical name and email.

    A `.mailmap` entry is an explicit statement of intent by the repository
    owner and always wins. Entries written against either GitHub noreply
    form are honoured, the raw address taking precedence. An address that
    `.mailmap` does not cover falls back to noreply normalisation.

    Args:
        name: Author name as recorded on the commit.
        email: Author email as recorded on the commit.
        mailmap: Parsed mappings from `_read_mailmap`.

    Returns:
        A tuple of (canonical_name, canonical_email).
    """
    normalised = _normalise_github_noreply(email)

    mapped = mailmap.lookup(name, email)
    if mapped is None and normalised != email:
        mapped = mailmap.lookup(name, normalised)

    if mapped is not None:
        canonical_name, canonical_email = mapped
        # The email-only form replaces the address but keeps the name.
        return (name if canonical_name is None else canonical_name), canonical_email

    return name, normalised


def _sum_numstat(block: str) -> tuple[int, int]:
    r"""Total the insertions and deletions in a `git log --numstat` block.

    Each numstat line is `<added>\t<deleted>\t<path>`. Binary files report
    a literal `-` for both counts and contribute zero, matching the
    behaviour of the per-commit diff this replaced.

    Args:
        block: The numstat lines belonging to a single commit. May be
            empty for a commit that changed no files.

    Returns:
        A tuple of (lines_added, lines_deleted).
    """
    added = 0
    deleted = 0
    for line in block.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        raw_added, raw_deleted = fields[0], fields[1]
        if raw_added.isdigit():
            added += int(raw_added)
        if raw_deleted.isdigit():
            deleted += int(raw_deleted)
    return added, deleted


class GitReader:
    """Reads commit history and metadata from a local Git repository.

    Args:
        repo_path: Path to the repository root. Must contain a .git directory.

    Raises:
        RepositoryError: If the path does not contain a valid Git repository,
            does not exist, or cannot be read.
    """

    def __init__(self, repo_path: Path) -> None:
        """Initialise the reader and validate the repository path.

        Args:
            repo_path: Path to the Git repository root.

        Raises:
            RepositoryError: If the path is not a valid readable Git repository.
        """
        self._mailmap_applied = False
        self.unmatched_exclusions: tuple[str, ...] = ()
        try:
            self._repo = Repo(str(repo_path), search_parent_directories=False)
        except InvalidGitRepositoryError as exc:
            raise RepositoryError(
                f"'{repo_path}' is not a valid Git repository. "
                "Ensure the path contains a .git directory."
            ) from exc
        except NoSuchPathError as exc:
            raise RepositoryError(f"'{repo_path}' does not exist.") from exc
        self._repo_path = repo_path.resolve()

    def read_commits(
        self,
        branch: str | None,
        since: datetime.date | None,
        until: datetime.date | None,
        exclude_authors: list[str],
    ) -> list[Commit]:
        """Read all commits within the specified analysis window.

        The entire history is read in one `git log --numstat` subprocess,
        including per-commit line counts.

        Merge commits are unconditionally excluded. Author filtering
        matches against name, resolved email, and the raw email as
        recorded on the commit, case-insensitively.

        The until date is inclusive: commits on that calendar day are
        included in the result.

        Args:
            branch: Branch to read from. Uses the repository's active
                branch if None.
            since: Include only commits on or after this date. No lower
                bound is applied if None.
            until: Include only commits on or before this date. No upper
                bound is applied if None.
            exclude_authors: Author names or email addresses to exclude.
                Matching is case-insensitive.

        Returns:
            A list of Commit objects sorted by timestamp descending
            (most recent first).

        Raises:
            RepositoryError: If the specified branch does not exist.
            EmptyRepositoryError: If no commits match the specified window
                after filtering.
        """
        rev = branch or self._resolve_active_branch()

        # A revision beginning with `-` is parsed by git as an OPTION, not a
        # ref. The trailing `--` below separates revisions from paths; it does
        # not protect the revision slot. Without this guard, a branch value of
        # `--output=/path/to/file` makes `git log` write its output over that
        # file -- and `branch` can arrive from an auto-discovered reveille.toml
        # sitting in a repository the attacker controls, so the victim needs
        # only to run `reveille generate` inside a clone.
        if rev.startswith("-"):
            raise RepositoryError(
                f"Refusing to use {rev!r} as a revision: a value beginning with "
                "'-' is interpreted by git as a command-line option rather than "
                "a branch. If a ref really has this name, rename it."
            )

        log_args, rev_list_args = _build_log_args(
            rev, since, until, self._supports_since_as_filter()
        )

        # The mailmap is read first, because an exclusion has to be expanded
        # through it: --exclude-author names a person, and a person with a
        # mailmap has more than one identity.
        mailmap = self._read_mailmap()
        self._mailmap_applied = bool(mailmap.by_email or mailmap.by_name_and_email)

        exclude_set = _expand_exclusions(exclude_authors, mailmap)

        # An unborn HEAD means the repository is readable but has no commits
        # at all. That is a negative answer, not a failure to read, so it
        # must surface as EmptyRepositoryError like an empty analysis window
        # rather than as the RepositoryError that `git log` would produce.
        if not self._repo.head.is_valid():
            raise EmptyRepositoryError(
                f"Repository at '{self._repo_path}' contains no commits. "
                "Make at least one commit before generating a report."
            )

        # `git log --format` interpolates the author name verbatim, and a name
        # can contain the separators this reader splits on -- so one crafted
        # commit can inject an entire extra record and fabricate a contributor.
        # Scrubbing the fields afterwards cannot help: by then the split has
        # already happened.
        #
        # So take the object names from git itself, where the attacker has no
        # say. `rev-list` computes each SHA rather than echoing text, and does
        # no diff work, so it is cheap beside the --numstat read. A record whose
        # SHA is not in this set did not come from a commit.
        _logger.debug("git rev-list %s", " ".join(rev_list_args))
        try:
            authentic_shas = {
                line.strip()
                for line in str(self._repo.git.rev_list(*rev_list_args)).splitlines()
                if line.strip()
            }
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to enumerate commits on branch '{rev}'. "
                "Verify the branch exists in this repository."
            ) from exc

        _logger.debug("git log %s", " ".join(log_args))
        try:
            raw_log = self._repo.git.log(*log_args)
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to read commits from branch '{rev}'. "
                f"Verify the branch name is correct. Detail: {exc}"
            ) from exc

        commits: list[Commit] = []
        matched: set[str] = set()
        for record in raw_log.split(_RECORD_SEP):
            commit = _parse_log_record(record, mailmap, exclude_set, authentic_shas, matched)
            if commit is not None:
                commits.append(commit)

        # A filter that matched nothing is almost always a typo, and silence
        # makes it indistinguishable from one that worked. This matters most
        # for the case the filter exists to serve: somebody asked to be left
        # out, and the report was generated believing they had been.
        unmatched = sorted(exclude_set - matched)
        if unmatched:
            _logger.warning("--exclude-author matched no commits for: %s", ", ".join(unmatched))
            self.unmatched_exclusions = tuple(unmatched)

        if not commits:
            raise EmptyRepositoryError(
                "No commits found within the specified analysis window. "
                "Try widening the date range or removing author filters."
            )

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
        """Aggregate raw commits into per-contributor statistics.

        Contributor identity is keyed on author email (lowercased).
        Where a contributor has used multiple display names, the name
        from the most recent commit is used.

        Args:
            commits: Raw commit list returned by read_commits.
            min_commits: Exclude contributors with fewer than this many
                commits in the analysis window.

        Returns:
            A list of ContributorStats sorted by commit count descending.
            Contributors below the min_commits threshold are excluded.
        """
        grouped: dict[str, list[Commit]] = defaultdict(list)
        for commit in commits:
            grouped[commit.author_email.lower()].append(commit)

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
        """Read repository-level metadata.

        The repository name is derived from the directory name of the
        repository root. The remote URL is read from the 'origin' remote
        if present, falling back to the first available remote.

        Args:
            total_commits: Total commit count within the analysis window.
            unique_contributors: Unique contributor count after filtering.
            analysis_since: Start of the analysis window.
            analysis_until: End of the analysis window.
            branch: The ref the analysis walked, as requested by the caller.
                When omitted the active branch is used -- the same fallback
                `read_commits` applies, so the two cannot disagree.

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
        """Return the current active branch name.

        Falls back to 'HEAD' when the repository is in a detached HEAD
        state, which occurs in shallow clones and CI checkout scenarios.

        Returns:
            The branch name string, or 'HEAD' for detached HEAD state.
        """
        try:
            return self._repo.active_branch.name
        except TypeError:
            return "HEAD"

    def resolve_head_sha(self, branch: str | None = None) -> str | None:
        """Return the full SHA at the tip of the ref that was analysed.

        This is what pins a report to an exact repository state: the same SHA
        with the same filters must reproduce the same numbers.

        Args:
            branch: The ref to resolve. Defaults to the active branch, matching
                `read_commits` and `read_metadata`.

        Returns:
            The 40-character commit SHA, or None if the ref cannot be resolved
            -- an empty repository or an unborn branch, neither of which is an
            error worth failing a report over.
        """
        rev = branch or self._resolve_active_branch()
        try:
            return str(self._repo.commit(rev).hexsha)
        except Exception:
            return None

    @property
    def mailmap_applied(self) -> bool:
        """Whether a non-empty `.mailmap` was applied during aggregation.

        False until `read_commits` has run, because that is where the file is
        read. Identity merging materially changes contributor
        counts, so a report that used one is not comparable with a report that
        did not.
        """
        return self._mailmap_applied

    def _supports_since_as_filter(self) -> bool:
        """Whether the installed git understands `--since-as-filter`.

        Added in git 2.37 (2022). Probed rather than assumed, because falling
        back is better than failing: on an older git the window may
        under-report over non-chronological history, which is the behaviour
        every previous release had.

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
        """Return the URL of the origin remote, or the first available remote.

        Returns:
            The remote URL string, or None if no remotes are configured.
        """
        if not self._repo.remotes:
            return None
        try:
            return str(self._repo.remotes["origin"].url)
        except IndexError:
            return str(self._repo.remotes[0].url)

    def _read_mailmap(self) -> _Mailmap:
        """Read and parse the .mailmap file from the repository root.

        All four forms documented in gitmailmap(5) are supported. See
        `_Mailmap` for how the parsed entries are looked up. A comment
        (`#`) runs to end of line, and blank lines are ignored, matching
        Git. Malformed lines are skipped silently: a `.mailmap` is
        frequently hand-edited, and refusing to produce a report over one
        bad line would be a worse failure than ignoring it.

        Returns:
            The parsed lookup tables. Empty if the file is absent or
            unreadable.
        """
        mailmap_path = self._repo_path / ".mailmap"
        if not mailmap_path.exists():
            return _Mailmap()

        try:
            lines = mailmap_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return _Mailmap()

        mailmap = _Mailmap()
        for line in lines:
            # A comment runs to end of line, not just whole-line comments.
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue

            m4 = _MAILMAP_FOUR_FIELD.match(stripped)
            if m4:
                mailmap.by_name_and_email[(m4.group(3).strip().lower(), m4.group(4).lower())] = (
                    m4.group(1).strip(),
                    m4.group(2).lower(),
                )
                continue

            m3 = _MAILMAP_THREE_FIELD.match(stripped)
            if m3:
                mailmap.by_email[m3.group(3).lower()] = (
                    m3.group(1).strip(),
                    m3.group(2).lower(),
                )
                continue

            m2 = _MAILMAP_EMAIL_ONLY.match(stripped)
            if m2:
                # Only the email is replaced; the commit's name is kept,
                # which None signals to _resolve_identity.
                mailmap.by_email[m2.group(2).lower()] = (None, m2.group(1).lower())
                continue

            m1 = _MAILMAP_NAME_ONLY.match(stripped)
            if m1:
                email = m1.group(2).lower()
                mailmap.by_email[email] = (m1.group(1).strip(), email)

        return mailmap


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


def _strip_control_chars(value: str) -> str:
    """Remove C0 control characters from a git identity field.

    Git's ident sanitiser strips `<`, `>` and newlines but leaves other control
    characters intact, so an author name written directly into a commit object
    can contain the record and field separators this reader splits on. One such
    commit was enough to fabricate three contributors and promote an invented
    name to the top ranking tier.

    Args:
        value: A raw author name or address straight from `git log`.

    Returns:
        The value with every C0 control character and DEL removed.
    """
    return _CONTROL_CHARS_RE.sub("", value)


def _parse_log_record(
    record: str,
    mailmap: _Mailmap,
    exclude_set: set[str],
    authentic_shas: set[str],
    matched: set[str],
) -> Commit | None:
    """Turn one `git log` record into a Commit, or reject it.

    Every rejection path here is a defence rather than a convenience. A commit
    object written directly with `git hash-object --literally` can carry
    control characters in its author fields and a timestamp that is not a
    number, and Git will replay both faithfully. A record that survives all of
    the checks below is one this reader is willing to attribute to a person.

    Args:
        record: One record from the split log output, without its separator.
        mailmap: Parsed `.mailmap` lookup tables.
        exclude_set: Lowercased names and addresses to drop.
        authentic_shas: Object names git itself reported for this revision. A
            record whose SHA is absent was not produced by a commit.
        matched: Mutated in place with every exclusion value that matched, so
            the caller can report the ones that never did.

    Returns:
        The parsed Commit, or None if the record is empty, malformed,
        excluded by filter, or carries an unusable timestamp.
    """
    if not record.strip():
        return None

    header, _, numstat_block = record.partition("\n")
    fields = header.split(_FIELD_SEP)
    if len(fields) != 4:
        return None

    sha, raw_name, raw_email, committed_at = fields

    # A crafted author name can produce a record that *looks* well formed --
    # right field count, forty hex characters -- so shape alone is not enough.
    # Membership in the set git computed is.
    if not _SHA_RE.fullmatch(sha) or sha not in authentic_shas:
        return None

    # An author field carrying our own separators can split one commit into
    # several fabricated contributors -- and the ranking then promotes an
    # invented name into a tier. Scrub before trusting.
    raw_name = _truncate(_strip_control_chars(raw_name), _MAX_NAME_LENGTH)
    raw_email = _truncate(_strip_control_chars(raw_email), _MAX_EMAIL_LENGTH)

    author_name, author_email = _resolve_identity(raw_name, raw_email, mailmap)

    # Both the resolved and the raw identity are matched, so an
    # --exclude-author value copied from `git log` still works after
    # normalisation. The raw *name* matters as much as the raw address: with a
    # .mailmap renaming "Bob Jones" to "Robert Jones", `git log --format=%an`
    # shows the old name, so that is what a user copies -- and matching only
    # the resolved name would leave the person in the report while exiting 0.
    hits = exclude_set & {
        author_name.lower(),
        author_email.lower(),
        raw_name.lower(),
        raw_email.lower(),
    }
    if hits:
        matched |= hits
        return None

    try:
        timestamp = datetime.datetime.fromtimestamp(int(committed_at), tz=datetime.UTC)
    except (ValueError, OverflowError, OSError):
        # A hand-written commit object can carry a timestamp that is not a
        # number, or one far outside the platform's range. That is one unusable
        # record, not a reason to abandon the whole report.
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
) -> tuple[list[str], list[str]]:
    """Build the argument lists for the numstat read and the SHA allowlist.

    Returned as a pair because the two commands must agree on revision
    selection and on the date window. `rev-list` shares those with `log` but
    rejects diff-formatting options such as `--numstat`, so the lists are built
    explicitly rather than one filtered from the other -- if the windows drifted
    apart the allowlist would stop covering every record the log returns.

    Args:
        rev: The revision to walk. Already checked not to begin with `-`.
        since: Inclusive start of the analysis window, if any.
        until: Inclusive end of the analysis window, if any.
        supports_since_as_filter: Whether the installed git understands
            `--since-as-filter` (added in git 2.37). When it does not, the
            greedy `--after` is used and a narrow window over non-chronological
            history may under-report.

    Returns:
        A `(log_args, rev_list_args)` pair.
    """
    log_args: list[str] = ["--no-merges", "--numstat", _LOG_FORMAT]
    rev_list_args: list[str] = ["--no-merges"]

    # Boundaries are pinned to UTC. Git parses a bare `YYYY-MM-DD` in the
    # machine's LOCAL timezone, while every timestamp this reader produces is
    # rendered in UTC -- so the same repository and the same `--since` gave
    # different answers on different machines. Measured with one commit at
    # 2024-06-10T22:00Z and `--since 2024-06-11`: empty under UTC and under
    # America/Los_Angeles, one commit under Pacific/Auckland.
    #
    # An explicit offset removes the machine from the answer, which is also
    # what `--deterministic` needs in order to mean anything.
    if since is not None:
        boundary = f"{since.isoformat()}T00:00:00+00:00"
        # `--since-as-filter`, not `--since`/`--after`. Git's `--since` is
        # *greedy*: the walk stops at the first commit older than the boundary
        # and does not resume, so anything reachable further down the parent
        # chain is never examined -- even when it is squarely inside the
        # window. Rebases, cherry-picks, merged old branches and ordinary clock
        # skew between contributors all produce that shape.
        #
        # Measured on a three-commit chain dated 01-15, 01-01, 01-20 with
        # `--since 2024-01-08`: `--after` returned one commit, silently losing
        # the 01-20 one; `--since-as-filter` returned both. A silently short
        # answer is the worst kind for a reporting tool.
        #
        # `--before`/`--until` needs no equivalent: the walk starts at the
        # newest end, so a too-new commit does not terminate it.
        flag = "--since-as-filter" if supports_since_as_filter else "--after"
        log_args.append(f"{flag}={boundary}")
        rev_list_args.append(f"{flag}={boundary}")
    if until is not None:
        # One day past the boundary, so `--until` is inclusive of its own date.
        inclusive_until = (until + datetime.timedelta(days=1)).isoformat()
        boundary = f"{inclusive_until}T00:00:00+00:00"
        log_args.append(f"--before={boundary}")
        rev_list_args.append(f"--before={boundary}")

    # `--end-of-options` stops git parsing anything after it as an option; the
    # trailing `--` disambiguates the revision from a path of the same name.
    for args in (log_args, rev_list_args):
        args.extend(["--end-of-options", rev, "--"])

    return log_args, rev_list_args


def _expand_exclusions(exclude_authors: list[str], mailmap: _Mailmap) -> set[str]:
    """Expand each exclusion to every identity the `.mailmap` ties it to.

    `--exclude-author` is documented as removing a *person*, and a person with
    a `.mailmap` has more than one identity. Matching only the literal value
    dropped the commits authored under the address the user named and left
    every other alias in place -- so excluding somebody's old address removed
    one commit and left them in the report under the new one, exit 0, no
    diagnostic. For the one flag whose stated purpose is privacy, being
    approximate in that direction is the wrong way round.

    Args:
        exclude_authors: Raw values as supplied, by name or by address.
        mailmap: The parsed `.mailmap` for this repository.

    Returns:
        A lowercased set containing each supplied value plus, for any value the
        mailmap recognises, the canonical name and address it maps to.
    """
    expanded = {entry.lower() for entry in exclude_authors}

    for entry in list(expanded):
        canonical = mailmap.by_email.get(entry)
        if canonical is not None:
            canonical_name, canonical_email = canonical
            if canonical_name:
                expanded.add(canonical_name.lower())
            expanded.add(canonical_email.lower())

        # The four-field form is keyed on (commit name, commit address), so a
        # value naming either half expands to that entry's canonical identity.
        for (commit_name, commit_email), (name, email) in mailmap.by_name_and_email.items():
            if entry in (commit_name, commit_email):
                if name:
                    expanded.add(name.lower())
                expanded.add(email.lower())

    return expanded
