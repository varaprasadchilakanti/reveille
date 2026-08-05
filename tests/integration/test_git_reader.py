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
        2024-04-10  Alice   refactor: simplify logic   +0 -1
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


@pytest.fixture(scope="module")
def fixture_repo_with_mailmap(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a Git repository with a .mailmap file for alias resolution testing.

    Commit history (6 commits):
        2024-03-01  alice@example.com       feat: initial commit
        2024-03-15  bob@example.com         feat: add module_b
        2024-03-20  alice@example.com       fix: correct calculation
        2024-04-10  alice@example.com       refactor: simplify logic
        2024-04-15  bob@example.com         chore: update constants
        2024-04-20  alice-old@example.com   feat: legacy contribution

    .mailmap (untracked) maps alice-old@example.com to alice@example.com.
    The file also contains two malformed lines to verify silent-skip behaviour.
    """
    repo_path = tmp_path_factory.mktemp("fixture_repo_mailmap")

    def run(args: list[str], env_override: dict[str, str] | None = None) -> None:
        env = {**os.environ, **(env_override or {})}
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

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
    alice_old_env = {
        "GIT_AUTHOR_NAME": "Alice Old",
        "GIT_AUTHOR_EMAIL": "alice-old@example.com",
        "GIT_COMMITTER_NAME": "Alice Old",
        "GIT_COMMITTER_EMAIL": "alice-old@example.com",
    }

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "alice@example.com"])
    run(["git", "config", "user.name", "Alice"])

    (repo_path / "module_a.py").write_text("x = 1\ny = 2\nz = 3\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "feat: initial commit", "--date=2024-03-01T10:00:00+00:00"],
        env_override={**alice_env, "GIT_COMMITTER_DATE": "2024-03-01T10:00:00+00:00"},
    )

    (repo_path / "module_b.py").write_text("a = 10\nb = 20\nc = 30\nd = 40\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "feat: add module_b", "--date=2024-03-15T14:00:00+00:00"],
        env_override={**bob_env, "GIT_COMMITTER_DATE": "2024-03-15T14:00:00+00:00"},
    )

    (repo_path / "module_a.py").write_text("x = 1\ny = 2\nz = 4\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "fix: correct calculation", "--date=2024-03-20T09:00:00+00:00"],
        env_override={**alice_env, "GIT_COMMITTER_DATE": "2024-03-20T09:00:00+00:00"},
    )

    (repo_path / "module_a.py").write_text("x = 1\nz = 4\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "refactor: simplify logic", "--date=2024-04-10T11:00:00+00:00"],
        env_override={**alice_env, "GIT_COMMITTER_DATE": "2024-04-10T11:00:00+00:00"},
    )

    (repo_path / "module_b.py").write_text("a = 10\nb = 20\nc = 30\nd = 50\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "chore: update constants", "--date=2024-04-15T16:00:00+00:00"],
        env_override={**bob_env, "GIT_COMMITTER_DATE": "2024-04-15T16:00:00+00:00"},
    )

    (repo_path / "module_c.py").write_text("c = 99\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "feat: legacy contribution", "--date=2024-04-20T12:00:00+00:00"],
        env_override={**alice_old_env, "GIT_COMMITTER_DATE": "2024-04-20T12:00:00+00:00"},
    )

    # .mailmap left untracked — _read_mailmap reads from disk, not git objects.
    (repo_path / ".mailmap").write_text(
        "# Canonical identity mappings\n"
        "Alice <alice@example.com> <alice-old@example.com>\n"
        "this line is malformed and should be silently skipped\n"
        "<also malformed>\n",
        encoding="utf-8",
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


# ------------------------------------------------------------------
# Mailmap alias resolution tests
# ------------------------------------------------------------------


@pytest.mark.integration
class TestMailmapResolution:
    """Tests for .mailmap canonical identity resolution in GitReader."""

    def test_aliased_email_commits_aggregate_under_canonical_identity(
        self, fixture_repo_with_mailmap: Path
    ) -> None:
        """Commits made under the alias email count toward the canonical contributor."""
        reader = GitReader(fixture_repo_with_mailmap)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(commits=commits, min_commits=1)
        alice = next(s for s in stats if s.email == "alice@example.com")
        assert alice.commit_count == 4

    def test_alias_email_does_not_appear_as_separate_contributor(
        self, fixture_repo_with_mailmap: Path
    ) -> None:
        """The alias email must not produce a separate ContributorStats entry."""
        reader = GitReader(fixture_repo_with_mailmap)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(commits=commits, min_commits=1)
        emails = {s.email for s in stats}
        assert "alice-old@example.com" not in emails

    def test_missing_mailmap_does_not_raise(self, fixture_repo: Path) -> None:
        """read_commits succeeds on a repository with no .mailmap file."""
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        assert len(commits) == 5

    def test_malformed_mailmap_lines_are_silently_skipped(
        self, fixture_repo_with_mailmap: Path
    ) -> None:
        """Malformed lines do not raise; valid mappings surrounding them still apply."""
        reader = GitReader(fixture_repo_with_mailmap)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        emails = {c.author_email.lower() for c in commits}
        assert "alice-old@example.com" not in emails
        assert "alice@example.com" in emails


# ------------------------------------------------------------------
# Line count tests
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def line_count_edge_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a repository exercising the numstat parser's edge cases.

    Commit history (chronological):
        Alice   feat: add text file      +2 -0
        Alice   feat: add binary file    binary, reported as +0 -0
        Alice   chore: empty commit      no files changed, +0 -0
    """
    repo_path = tmp_path_factory.mktemp("line_count_edge_repo")

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
    }

    def run(args: list[str]) -> None:
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "alice@example.com"])
    run(["git", "config", "user.name", "Alice"])

    (repo_path / "module_a.py").write_text("x = 1\ny = 2\n")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "feat: add text file"])

    # A PNG header followed by a NUL byte: git classifies this as binary
    # and reports '-' for both counts rather than a line delta.
    (repo_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02\x03")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "feat: add binary file"])

    run(["git", "commit", "--allow-empty", "-m", "chore: empty commit"])

    return repo_path


@pytest.mark.integration
class TestLineCounts:
    """Tests for per-commit line counts read from `git log --numstat`."""

    def test_line_counts_match_fixture_history(self, fixture_repo: Path) -> None:
        """Per-commit counts match the history documented on the fixture."""
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        # Fixture order is most recent first; the docstring lists it chronologically.
        counts = [(c.lines_added, c.lines_deleted) for c in reversed(commits)]
        assert counts == [(3, 0), (4, 0), (1, 1), (0, 1), (1, 1)]

    def test_repository_totals_are_correct(self, fixture_repo: Path) -> None:
        """Aggregate totals across the whole fixture history."""
        reader = GitReader(fixture_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        assert sum(c.lines_added for c in commits) == 9
        assert sum(c.lines_deleted for c in commits) == 3

    def test_binary_file_commit_reports_zero_lines(self, line_count_edge_repo: Path) -> None:
        """A binary-only commit contributes no lines rather than raising."""
        reader = GitReader(line_count_edge_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        # Chronological: text (+2), binary (0), empty (0).
        chronological = list(reversed(commits))
        assert (chronological[1].lines_added, chronological[1].lines_deleted) == (0, 0)

    def test_empty_commit_reports_zero_lines(self, line_count_edge_repo: Path) -> None:
        """A commit that changed no files yields zero counts and is still read."""
        reader = GitReader(line_count_edge_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        assert len(commits) == 3
        chronological = list(reversed(commits))
        assert (chronological[2].lines_added, chronological[2].lines_deleted) == (0, 0)

    def test_root_commit_counts_full_tree(self, line_count_edge_repo: Path) -> None:
        """The root commit has no parent; its diff is against the empty tree."""
        reader = GitReader(line_count_edge_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        root = next(reversed(commits))
        assert root.lines_added == 2
        assert root.lines_deleted == 0


# ------------------------------------------------------------------
# GitHub noreply identity tests
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def noreply_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a repository where one account uses both GitHub noreply forms.

    Commit history (chronological):
        Alice  140685918+alice@users.noreply.github.com   prefixed form
        Alice  alice@users.noreply.github.com             legacy form
        Bob    bob@example.com                            ordinary address

    Alice is one GitHub account whose commits span the 2017 address change.
    Without normalisation she aggregates as two separate contributors.
    """
    repo_path = tmp_path_factory.mktemp("noreply_repo")

    def run(args: list[str], env_override: dict[str, str] | None = None) -> None:
        env = {**os.environ, **(env_override or {})}
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

    def identity(name: str, email: str) -> dict[str, str]:
        return {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "alice@example.com"])
    run(["git", "config", "user.name", "Alice"])

    (repo_path / "a.py").write_text("x = 1\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "feat: prefixed form"],
        env_override=identity("Alice", "140685918+alice@users.noreply.github.com"),
    )

    (repo_path / "b.py").write_text("y = 2\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "feat: legacy form"],
        env_override=identity("Alice", "alice@users.noreply.github.com"),
    )

    (repo_path / "c.py").write_text("z = 3\n")
    run(["git", "add", "."])
    run(
        ["git", "commit", "-m", "feat: ordinary address"],
        env_override=identity("Bob", "bob@example.com"),
    )

    return repo_path


@pytest.mark.integration
class TestGithubNoreplyIdentity:
    """Tests for GitHub noreply address folding in read_commits."""

    def test_github_noreply_prefix_stripped(self, noreply_repo: Path) -> None:
        reader = GitReader(noreply_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        emails = {c.author_email for c in commits}
        assert "140685918+alice@users.noreply.github.com" not in emails
        assert "alice@users.noreply.github.com" in emails

    def test_non_noreply_email_unaffected(self, noreply_repo: Path) -> None:
        reader = GitReader(noreply_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        assert "bob@example.com" in {c.author_email for c in commits}

    def test_both_noreply_forms_aggregate_as_one_contributor(self, noreply_repo: Path) -> None:
        """The headline fix: one account must not appear as two contributors."""
        reader = GitReader(noreply_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        stats = reader.aggregate_contributor_stats(commits=commits, min_commits=1)
        assert len(stats) == 2
        alice = next(s for s in stats if s.email == "alice@users.noreply.github.com")
        assert alice.commit_count == 2

    def test_exclusion_by_raw_prefixed_address_still_works(self, noreply_repo: Path) -> None:
        """An --exclude-author copied from `git log` matches the raw form."""
        reader = GitReader(noreply_repo)
        commits = reader.read_commits(
            branch=None,
            since=None,
            until=None,
            exclude_authors=["140685918+alice@users.noreply.github.com"],
        )
        assert len(commits) == 2

    def test_exclusion_by_normalised_address_matches_both_forms(self, noreply_repo: Path) -> None:
        """An --exclude-author copied from report output removes the account."""
        reader = GitReader(noreply_repo)
        commits = reader.read_commits(
            branch=None,
            since=None,
            until=None,
            exclude_authors=["alice@users.noreply.github.com"],
        )
        assert len(commits) == 1
        assert commits[0].author_email == "bob@example.com"

    def test_mailmap_entry_overrides_normalisation(self, noreply_repo: Path) -> None:
        """An explicit .mailmap statement wins over automatic folding."""
        mailmap = noreply_repo / ".mailmap"
        mailmap.write_text(
            "Alice Real <alice@example.com> <140685918+alice@users.noreply.github.com>\n"
        )
        try:
            reader = GitReader(noreply_repo)
            commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
            emails = {c.author_email for c in commits}
            assert "alice@example.com" in emails
        finally:
            mailmap.unlink()


# ------------------------------------------------------------------
# Full .mailmap specification tests
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def four_field_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a repository exercising all four gitmailmap(5) forms.

    Commit history (chronological):
        Daniel Brown <daniel@oldcorp.com>   four-field target
        Erica Stone  <daniel@oldcorp.com>   same address, different name
        Frank Lee    <frank-old@example.com>  email-only target
        Grace Kim    <grace@example.com>    name-only target

    Erica shares Daniel's old address, which is what the four-field form
    exists to disambiguate: only Daniel's commits may be rewritten.
    """
    repo_path = tmp_path_factory.mktemp("four_field_repo")

    def run(args: list[str], env_override: dict[str, str] | None = None) -> None:
        env = {**os.environ, **(env_override or {})}
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True, env=env)

    def identity(name: str, email: str) -> dict[str, str]:
        return {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }

    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "seed@example.com"])
    run(["git", "config", "user.name", "Seed"])

    authors = [
        ("Daniel Brown", "daniel@oldcorp.com"),
        ("Erica Stone", "daniel@oldcorp.com"),
        ("Frank Lee", "frank-old@example.com"),
        ("Grace Kim", "grace@example.com"),
    ]
    for index, (name, email) in enumerate(authors):
        (repo_path / f"file_{index}.py").write_text(f"value = {index}\n")
        run(["git", "add", "."])
        run(["git", "commit", "-m", f"feat: commit {index}"], env_override=identity(name, email))

    (repo_path / ".mailmap").write_text(
        "# Canonical identities for this repository\n"
        "\n"
        "Dan Brown <dan@newcorp.com> Daniel Brown <daniel@oldcorp.com>\n"
        "<frank@example.com> <frank-old@example.com>\n"
        "Grace Kim-Watanabe <grace@example.com>  # married name\n"
    )

    return repo_path


@pytest.mark.integration
class TestMailmapFourFieldForm:
    """Tests for the four-field form: matched on commit name and email together."""

    def test_four_field_form_maps_old_name_and_email_to_canonical_identity(
        self, four_field_repo: Path
    ) -> None:
        reader = GitReader(four_field_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        daniel = next(c for c in commits if c.author_email == "dan@newcorp.com")
        assert daniel.author_name == "Dan Brown"

    def test_four_field_form_leaves_a_different_name_on_the_same_address(
        self, four_field_repo: Path
    ) -> None:
        """Erica shares Daniel's address and must not be rewritten as Daniel."""
        reader = GitReader(four_field_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        erica = next(c for c in commits if c.author_name == "Erica Stone")
        assert erica.author_email == "daniel@oldcorp.com"

    def test_four_field_and_three_field_coexist_in_same_mailmap(
        self, four_field_repo: Path
    ) -> None:
        """Every form in one file is parsed; none shadows another."""
        reader = GitReader(four_field_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        identities = {(c.author_name, c.author_email) for c in commits}
        assert identities == {
            ("Dan Brown", "dan@newcorp.com"),
            ("Erica Stone", "daniel@oldcorp.com"),
            ("Frank Lee", "frank@example.com"),
            ("Grace Kim-Watanabe", "grace@example.com"),
        }


@pytest.mark.integration
class TestMailmapEmailOnlyForm:
    """Tests for the email-only form: `<proper@email> <commit@email>`."""

    def test_email_is_replaced_and_commit_name_preserved(self, four_field_repo: Path) -> None:
        reader = GitReader(four_field_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        frank = next(c for c in commits if c.author_email == "frank@example.com")
        assert frank.author_name == "Frank Lee"

    def test_email_only_form_does_not_leak_angle_brackets_into_the_name(
        self, four_field_repo: Path
    ) -> None:
        """Regression: the line was previously parsed as a name-only entry,
        yielding the literal '<frank@example.com>' as a display name."""
        reader = GitReader(four_field_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        assert not any("<" in c.author_name for c in commits)


@pytest.mark.integration
class TestMailmapComments:
    """Tests for Git's comment handling in .mailmap."""

    def test_trailing_comment_is_stripped_from_an_entry(self, four_field_repo: Path) -> None:
        reader = GitReader(four_field_repo)
        commits = reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
        grace = next(c for c in commits if c.author_email == "grace@example.com")
        assert grace.author_name == "Grace Kim-Watanabe"
