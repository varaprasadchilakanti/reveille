"""Integration tests for reveille.adapters.git_reader.GitReader.

These tests run against a real Git repository created in a temporary
directory for each test session. They verify behaviour against the
actual git binary and GitPython library, not against mocks.
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader
from reveille.exceptions import EmptyRepositoryError, RepositoryError

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a temporary Git repository with a deterministic commit history.

    Commit history (chronological):
        2024-03-01  Alice   feat: initial commit       +3 -0
        2024-03-15  Bob     feat: add module_b         +4 -0
        2024-03-20  Alice   fix: correct calculation   +1 -1
        2024-04-10  Alice   refactor: simplify logic   +2 -3
        2024-04-15  Bob     chore: update constants    +1 -1

    Scope is module-level: the repository is created once and shared
    across all tests in this module to avoid the overhead of repeated
    git init and commit sequences.
    """
    repo_path = tmp_path_factory.mktemp("fixture_repo")

    def run(args: list[str], env_override: dict[str, str] | None = None) -> None:
        env = {**os.environ, **(env_override or {})}
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "alice@example.com"])
    run(["git", "config", "user.name", "Alice"])

    alice_env = {
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
    }
    bob_env = {
        "GIT_AUTHOR_NAME": "Bob",
        "GIT_AUTHOR_EMAIL": "bob@example.com",
        "GIT_COMMITTER_NAME": "Bob",
        "GIT_COMMITTER_EMAIL": "bob@example.com",
    }

    # Commit 1 — Alice, 2024-03-01
    (repo_path / "module_a.py").write_text("x = 1\ny = 2\nz = 3\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "feat: initial commit",
            "--date=2024-03-01T10:00:00+00:00",
        ],
        env_override={**alice_env, "GIT_COMMITTER_DATE": "2024-03-01T10:00:00+00:00"},
    )

    # Commit 2 — Bob, 2024-03-15
    (repo_path / "module_b.py").write_text("a = 10\nb = 20\nc = 30\nd = 40\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "feat: add module_b",
            "--date=2024-03-15T14:00:00+00:00",
        ],
        env_override={**bob_env, "GIT_COMMITTER_DATE": "2024-03-15T14:00:00+00:00"},
    )

    # Commit 3 — Alice, 2024-03-20
    (repo_path / "module_a.py").write_text("x = 1\ny = 2\nz = 4\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "fix: correct calculation",
            "--date=2024-03-20T09:00:00+00:00",
        ],
        env_override={**alice_env, "GIT_COMMITTER_DATE": "2024-03-20T09:00:00+00:00"},
    )

    # Commit 4 — Alice, 2024-04-10
    (repo_path / "module_a.py").write_text("x = 1\nz = 4\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "refactor: simplify logic",
            "--date=2024-04-10T11:00:00+00:00",
        ],
        env_override={**alice_env, "GIT_COMMITTER_DATE": "2024-04-10T11:00:00+00:00"},
    )

    # Commit 5 — Bob, 2024-04-15
    (repo_path / "module_b.py").write_text("a = 10\nb = 20\nc = 30\nd = 50\n")
    run(["git", "add", "."])
    run(
        [
            "git",
            "commit",
            "-m",
            "chore: update constants",
            "--date=2024-04-15T16:00:00+00:00",
        ],
        env_override={**bob_env, "GIT_COMMITTER_DATE": "2024-04-15T16:00:00+00:00"},
    )

    return repo_path


# ------------------------------------------------------------------
# Initialisation tests
# ------------------------------------------------------------------


@pytest.mark.integration
class TestGitReaderInit:
    """Tests for GitReader initialisation and path validation."""

    def test_valid_repository_initialises_without_error(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        assert reader is not None

    def test_non_existent_path_raises_repository_error(self, tmp_path: Path) -> None:
        with pytest.raises(RepositoryError, match="does not exist"):
            GitReader(tmp_path / "no_such_directory")

    def test_non_git_directory_raises_repository_error(self, tmp_path: Path) -> None:
        plain_dir = tmp_path / "plain"
        plain_dir.mkdir()
        with pytest.raises(RepositoryError, match="not a valid Git repository"):
            GitReader(plain_dir)


# ------------------------------------------------------------------
# read_commits tests
# ------------------------------------------------------------------


@pytest.mark.integration
class TestReadCommits:
    """Tests for GitReader.read_commits."""

    def test_returns_all_commits_without_filters(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        assert len(commits) == 5

    def test_commits_are_sorted_most_recent_first(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        timestamps = [c.timestamp for c in commits]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_since_filter_excludes_earlier_commits(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(
            branch=None,
            since=datetime.date(2024, 4, 1),
            until=None,
            exclude_authors=[],
        )
        assert len(commits) == 2
        for commit in commits:
            assert commit.timestamp.date() >= datetime.date(2024, 4, 1)

    def test_until_filter_is_inclusive(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(
            branch=None,
            since=None,
            until=datetime.date(2024, 3, 15),
            exclude_authors=[],
        )
        assert len(commits) == 2

    def test_date_range_filter_returns_correct_window(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(
            branch=None,
            since=datetime.date(2024, 3, 10),
            until=datetime.date(2024, 3, 25),
            exclude_authors=[],
        )
        assert len(commits) == 2

    def test_exclude_authors_by_email(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(
            branch=None,
            since=None,
            until=None,
            exclude_authors=["bob@example.com"],
        )
        assert all(c.author_email != "bob@example.com" for c in commits)
        assert len(commits) == 3

    def test_exclude_authors_is_case_insensitive(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(
            branch=None,
            since=None,
            until=None,
            exclude_authors=["BOB@EXAMPLE.COM"],
        )
        assert len(commits) == 3

    def test_empty_window_raises_empty_repository_error(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        with pytest.raises(EmptyRepositoryError):
            reader.read_commits(
                branch=None,
                since=datetime.date(2020, 1, 1),
                until=datetime.date(2020, 12, 31),
                exclude_authors=[],
            )

    def test_invalid_branch_raises_repository_error(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        with pytest.raises(RepositoryError):
            reader.read_commits(
                branch="nonexistent-branch-xyz",
                since=None,
                until=None,
                exclude_authors=[],
            )


# ------------------------------------------------------------------
# aggregate_contributor_stats tests
# ------------------------------------------------------------------


@pytest.mark.integration
class TestAggregateContributorStats:
    """Tests for GitReader.aggregate_contributor_stats."""

    def test_returns_one_entry_per_unique_contributor(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(
            commits=commits,
            min_commits=1,
        )
        assert len(stats) == 2

    def test_alice_has_three_commits(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(
            commits=commits,
            min_commits=1,
        )
        alice = next(s for s in stats if s.email == "alice@example.com")
        assert alice.commit_count == 3

    def test_sorted_by_commit_count_descending(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(
            commits=commits,
            min_commits=1,
        )
        counts = [s.commit_count for s in stats]
        assert counts == sorted(counts, reverse=True)

    def test_min_commits_filters_low_activity_contributors(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        # Bob has 2 commits. min_commits=3 should exclude him.
        stats = reader.aggregate_contributor_stats(
            commits=commits,
            min_commits=3,
        )
        assert len(stats) == 1
        assert stats[0].email == "alice@example.com"

    def test_active_days_counts_distinct_calendar_dates(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(
            commits=commits,
            min_commits=1,
        )
        alice = next(s for s in stats if s.email == "alice@example.com")
        # Alice committed on 3 distinct calendar dates.
        assert alice.active_days == 3


# ------------------------------------------------------------------
# read_metadata tests
# ------------------------------------------------------------------


@pytest.mark.integration
class TestReadMetadata:
    """Tests for GitReader.read_metadata."""

    def test_metadata_name_matches_directory_name(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        metadata = reader.read_metadata(
            total_commits=5,
            unique_contributors=2,
            analysis_since=datetime.date(2024, 3, 1),
            analysis_until=datetime.date(2024, 4, 30),
        )
        assert metadata.name == fixture_repo.name

    def test_metadata_reflects_passed_totals(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        metadata = reader.read_metadata(
            total_commits=5,
            unique_contributors=2,
            analysis_since=datetime.date(2024, 3, 1),
            analysis_until=datetime.date(2024, 4, 30),
        )
        assert metadata.total_commits == 5
        assert metadata.unique_contributors == 2

    def test_generated_at_is_utc_aware(self, fixture_repo: Path) -> None:
        reader = GitReader(fixture_repo)
        metadata = reader.read_metadata(
            total_commits=5,
            unique_contributors=2,
            analysis_since=datetime.date(2024, 3, 1),
            analysis_until=datetime.date(2024, 4, 30),
        )
        assert metadata.generated_at.tzinfo is not None
