"""Git repository reader adapter.

Translates raw GitPython data into typed domain models. This is the
only layer in Reveille that imports GitPython. All other layers
receive domain objects and have no knowledge of the underlying library.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from reveille.domain.models import Commit, ContributorStats, RepositoryMetadata


class GitReader:
    """Reads commit history and metadata from a local Git repository.

    Args:
        repo_path: Path to the repository root. Must contain a .git directory.

    Raises:
        RepositoryError: If the path is not a valid Git repository.

    Note:
        Full implementation scheduled for feat/git-data-layer.
    """

    def __init__(self, repo_path: Path) -> None:
        """Initialise the reader and validate the repository path.

        Args:
            repo_path: Path to the Git repository root.

        Raises:
            RepositoryError: If the path does not contain a valid
                Git repository.
        """
        raise NotImplementedError(
            "GitReader.__init__ is not yet implemented. "
            "Scheduled for feat/git-data-layer."
        )

    def read_commits(
        self,
        branch: str | None,
        since: datetime.date | None,
        until: datetime.date | None,
        exclude_authors: list[str],
    ) -> list[Commit]:
        """Read all commits within the specified analysis window.

        Args:
            branch: Branch to read from. Uses the default branch if None.
            since: Include only commits on or after this date.
            until: Include only commits on or before this date.
            exclude_authors: Author names or emails to exclude.

        Returns:
            A list of Commit objects sorted by timestamp descending.

        Raises:
            EmptyRepositoryError: If no commits match the specified window.
        """
        raise NotImplementedError(
            "GitReader.read_commits is not yet implemented. "
            "Scheduled for feat/git-data-layer."
        )

    def aggregate_contributor_stats(
        self,
        commits: list[Commit],
        min_commits: int,
        window_start: datetime.date,
        window_end: datetime.date,
    ) -> list[ContributorStats]:
        """Aggregate raw commits into per-contributor statistics.

        Args:
            commits: Raw commit list returned by read_commits.
            min_commits: Exclude contributors below this commit threshold.
            window_start: Start of the analysis window.
            window_end: End of the analysis window.

        Returns:
            A list of ContributorStats, one per qualifying contributor.
        """
        raise NotImplementedError(
            "GitReader.aggregate_contributor_stats is not yet implemented. "
            "Scheduled for feat/git-data-layer."
        )

    def read_metadata(
        self,
        total_commits: int,
        unique_contributors: int,
        analysis_since: datetime.date,
        analysis_until: datetime.date,
    ) -> RepositoryMetadata:
        """Read repository-level metadata.

        Args:
            total_commits: Total commit count within the analysis window.
            unique_contributors: Unique contributor count after filtering.
            analysis_since: Start of the analysis window.
            analysis_until: End of the analysis window.

        Returns:
            A populated RepositoryMetadata instance.
        """
        raise NotImplementedError(
            "GitReader.read_metadata is not yet implemented. "
            "Scheduled for feat/git-data-layer."
        )
