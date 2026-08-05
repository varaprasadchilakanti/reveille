"""Git repository reader adapter.

Translates raw GitPython data into typed domain models. This is the
only layer in Reveille that imports GitPython. All other layers
receive domain objects and have no knowledge of the underlying library.

Identity resolution uses author email as the canonical contributor key.
Author name is taken from the contributor's most recent commit, which
handles name changes over a repository's lifetime gracefully.

Merge commits are excluded from all analysis. They inflate line counts
and commit volumes without reflecting individual contributor activity.

Commit history is read in a single `git log --numstat` subprocess.
Reading per-commit line counts through GitPython's ``Commit.stats``
instead spawns one `git diff` per commit, which dominates runtime on
any repository large enough to care about.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import GitCommandError

from reveille.domain.models import Commit, ContributorStats, RepositoryMetadata
from reveille.exceptions import EmptyRepositoryError, RepositoryError

# Record and field delimiters for the single-pass `git log` read.
# ASCII 0x1E (record separator) and 0x1F (unit separator) are control
# characters that cannot appear in a commit header field, so they parse
# unambiguously where a printable delimiter would not.
_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"

_LOG_FORMAT = f"--format={_RECORD_SEP}%H{_FIELD_SEP}%an{_FIELD_SEP}%ae{_FIELD_SEP}%ct"


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
        matches against both name and email, case-insensitively.

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
        rev = branch or self._resolve_default_branch()

        log_args: list[str] = ["--no-merges", "--numstat", _LOG_FORMAT]
        if since is not None:
            log_args.append(f"--after={since.isoformat()}")
        if until is not None:
            # Add one day to make the until boundary inclusive.
            inclusive_until = until + datetime.timedelta(days=1)
            log_args.append(f"--before={inclusive_until.isoformat()}")
        # The trailing `--` disambiguates the revision from a path of the
        # same name, which git would otherwise report as ambiguous.
        log_args.extend([rev, "--"])

        exclude_set = {entry.lower() for entry in exclude_authors}

        try:
            raw_log = self._repo.git.log(*log_args)
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to read commits from branch '{rev}'. "
                f"Verify the branch name is correct. Detail: {exc}"
            ) from exc

        mailmap = self._read_mailmap()

        commits: list[Commit] = []
        for record in raw_log.split(_RECORD_SEP):
            if not record.strip():
                continue

            header, _, numstat_block = record.partition("\n")
            fields = header.split(_FIELD_SEP)
            if len(fields) != 4:
                continue

            sha, author_name, author_email, committed_at = fields

            email_key = author_email.lower()
            if email_key in mailmap:
                author_name, author_email = mailmap[email_key]

            if author_name.lower() in exclude_set or author_email.lower() in exclude_set:
                continue

            lines_added, lines_deleted = _sum_numstat(numstat_block)
            commits.append(
                Commit(
                    sha=sha,
                    author_name=author_name,
                    author_email=author_email,
                    timestamp=datetime.datetime.fromtimestamp(
                        int(committed_at),
                        tz=datetime.UTC,
                    ),
                    lines_added=lines_added,
                    lines_deleted=lines_deleted,
                )
            )

        if not commits:
            raise EmptyRepositoryError(
                "No commits found within the specified analysis window. "
                "Try widening the date range or removing author filters."
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

        Returns:
            A populated RepositoryMetadata instance.
        """
        remote_url = self._resolve_remote_url()

        return RepositoryMetadata(
            name=self._repo_path.name,
            remote_url=remote_url,
            default_branch=self._resolve_default_branch(),
            total_commits=total_commits,
            unique_contributors=unique_contributors,
            analysis_since=analysis_since,
            analysis_until=analysis_until,
            generated_at=datetime.datetime.now(tz=datetime.UTC),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_default_branch(self) -> str:
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

    def _read_mailmap(self) -> dict[str, tuple[str, str]]:
        """Read and parse the .mailmap file from the repository root.

        Supports the two-field form ("Proper Name <commit@email.xx>") and
        the three-field form ("Proper Name <canonical@email.xx> <commit@email.xx>").
        The two-field form updates the author name only; the email is unchanged.
        The three-field form updates both the author name and the email.
        # TODO: four-field form — "Proper Name <proper@email.xx> Other Name <commit@email.xx>"

        Returns:
            A dict mapping lowercased alias email to a
            (canonical_name, lowercased_canonical_email) tuple. Returns
            an empty dict if the .mailmap file is absent or unreadable.
        """
        mailmap_path = self._repo_path / ".mailmap"
        if not mailmap_path.exists():
            return {}

        try:
            lines = mailmap_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}

        _three_field = re.compile(r"^(.+?)\s+<([^>]+)>\s+<([^>]+)>\s*$")
        _two_field = re.compile(r"^(.+?)\s+<([^>]+)>\s*$")

        mapping: dict[str, tuple[str, str]] = {}
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m3 = _three_field.match(stripped)
            if m3:
                canonical_name = m3.group(1).strip()
                canonical_email = m3.group(2).lower()
                alias_email = m3.group(3).lower()
                mapping[alias_email] = (canonical_name, canonical_email)
                continue
            m2 = _two_field.match(stripped)
            if m2:
                canonical_name = m2.group(1).strip()
                email = m2.group(2).lower()
                mapping[email] = (canonical_name, email)

        return mapping
