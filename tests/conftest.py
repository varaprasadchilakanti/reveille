"""Shared pytest fixtures for Reveille's test suite.

Fixtures defined here are available to all test modules without
explicit import. Fixtures relevant to a single module are defined
locally in that module.
"""

from __future__ import annotations

import datetime

import pytest

from reveille.domain.models import Commit, ContributorStats


@pytest.fixture(autouse=True)
def _only_the_repositorys_own_git_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run every test with no global or system Git config, as CI has none of its own.

    A developer's config (an identity, `safe.directory = *`, signing) otherwise
    lets a test pass locally that fails in CI. A test that needs a global
    setting sets `GIT_CONFIG_GLOBAL` itself.
    """
    empty = tmp_path_factory.getbasetemp() / "empty.gitconfig"
    empty.touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture()
def sample_commit() -> Commit:
    """A single valid Commit instance for use in unit tests."""
    return Commit(
        sha="abc1234def5678",
        author_name="Test Author",
        author_email="author@example.com",
        timestamp=datetime.datetime(2024, 6, 15, 10, 0, 0),
        lines_added=42,
        lines_deleted=7,
    )


@pytest.fixture()
def sample_contributor_stats() -> ContributorStats:
    """A single valid ContributorStats instance for use in unit tests."""
    return ContributorStats(
        name="Test Author",
        email="author@example.com",
        commit_count=25,
        lines_added=1800,
        lines_deleted=400,
        active_days=18,
        first_commit_date=datetime.date(2024, 1, 5),
        last_commit_date=datetime.date(2024, 6, 15),
    )
