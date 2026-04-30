"""Git repository reader adapter.

Translates raw GitPython data into typed domain models. This is the
only layer in Reveille that imports GitPython. All other layers
receive domain objects and have no knowledge of the underlying library.

Identity resolution uses author email as the canonical contributor key.
Author name is taken from the contributor's most recent commit, which
handles name changes over a repository's lifetime gracefully.

Merge commits are excluded from all analysis. They inflate line counts
and commit volumes without reflecting individual contributor activity.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import GitCommandError

from reveille.domain.models import Commit, ContributorStats, RepositoryMetadata
from reveille.exceptions import EmptyRepositoryError, RepositoryError


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
        kwargs: dict[str, str | bool] = {"no_merges": True}

        if since is not None:
            kwargs["after"] = since.isoformat()
        if until is not None:
            # Add one day to make the until boundary inclusive.
            inclusive_until = until + datetime.timedelta(days=1)
            kwargs["before"] = inclusive_until.isoformat()

        exclude_set = {entry.lower() for entry in exclude_authors}

        try:
            raw_commits = list(
                self._repo.iter_commits(rev, **kwargs)  # type: ignore[arg-type]
                # GitPython's stub omits **kwargs from the iter_commits signature
                # despite the runtime implementation accepting them (base.py:iter_commits).
                # The call is correct at runtime. See mypy overrides for git.* in pyproject.toml.
            )
        except GitCommandError as exc:
            raise RepositoryError(
                f"Failed to read commits from branch '{rev}'. "
                f"Verify the branch name is correct. Detail: {exc}"
            ) from exc

        commits: list[Commit] = []
        for raw in raw_commits:
            author_name: str = raw.author.name or ""
            author_email: str = raw.author.email or ""

            if (
                author_name.lower() in exclude_set
                or author_email.lower() in exclude_set
            ):
                continue

            stats = raw.stats.total
            commits.append(
                Commit(
                    sha=raw.hexsha,
                    author_name=author_name,
                    author_email=author_email,
                    timestamp=datetime.datetime.fromtimestamp(
                        raw.committed_date,
                        tz=datetime.UTC,
                    ),
                    lines_added=stats.get("insertions", 0),
                    lines_deleted=stats.get("deletions", 0),
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
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> list[ContributorStats]:
        """Aggregate raw commits into per-contributor statistics.

        Contributor identity is keyed on author email (lowercased).
        Where a contributor has used multiple display names, the name
        from the most recent commit is used.

        Args:
            commits: Raw commit list returned by read_commits.
            min_commits: Exclude contributors with fewer than this many
                commits in the analysis window.
            window_start: Start of the analysis window. Stored on the
                returned stats for use by the ranking engine.
            window_end: End of the analysis window.

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
