"""Shared pytest fixtures for Reveille's test suite.

Fixtures defined here are available to all test modules without
explicit import. Fixtures relevant to a single module are defined
locally in that module.
"""

from __future__ import annotations

import datetime
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from reveille.domain.models import Commit, ContributorStats

_EMPTY_CONFIG_HOME = pytest.StashKey[Path]()


def pytest_configure(config: pytest.Config) -> None:
    """Run the whole session with no global or system Git config, as CI has none.

    A hook, not a fixture: module-scoped fixtures that build repositories run
    before any function-scoped fixture, and they must not see a developer's
    config either (an identity, `safe.directory = *`, signing turned on). Runs
    in every xdist worker. A test that needs a global setting sets
    `GIT_CONFIG_GLOBAL` itself with `monkeypatch`.
    """
    home = Path(tempfile.mkdtemp(prefix="reveille-tests-"))
    config.stash[_EMPTY_CONFIG_HOME] = home
    empty = home / "empty.gitconfig"
    empty.touch()
    os.environ["GIT_CONFIG_GLOBAL"] = str(empty)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the empty config's directory; each worker left one in the temporary directory."""
    home = config.stash.get(_EMPTY_CONFIG_HOME, None)
    if home is not None:
        shutil.rmtree(home, ignore_errors=True)


@pytest.fixture(autouse=True)
def _cli_state_reset() -> None:
    """Reset the CLI's per-process state, which one in-process run can leave set."""
    from reveille import cli

    cli._stderr_json["on"] = False
    cli._StageSpinner.line_open = False


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
