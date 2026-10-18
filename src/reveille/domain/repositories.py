# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Many repositories, one row each, about the repository and never a person (ADR 0026)."""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from reveille.domain.areas import is_automated
from reveille.domain.models import Commit

#: Beyond the window but within this many days of the last commit, a repository is quiet.
QUIET_UNTIL_DAYS = 365

Status = Literal["active", "quiet", "dormant", "empty", "not read"]

#: The order statuses are counted and listed in.
STATUSES: tuple[Status, ...] = ("active", "quiet", "dormant", "empty", "not read")


@dataclass(frozen=True)
class RepositoryActivity:
    """One repository's row.

    Attributes:
        path: Relative to the directory searched, with `/` separators.
        status: By the days since the last commit; see `status_of`.
        branch: The checked-out branch, or None when not read or detached.
        last_commit: The date (UTC) of the last non-merge commit, if any.
        days_since_last_commit: From that date to the window's end.
        commits: Non-merge commits in the window.
        people: Distinct identities in the window, automated accounts apart.
        automated_accounts: Distinct automated identities in the window.
        shallow: Whether only part of the history is present.
        reason: Why the repository was not read, for "not read".
    """

    path: str
    status: Status
    branch: str | None = None
    last_commit: datetime.date | None = None
    days_since_last_commit: int | None = None
    commits: int = 0
    people: int = 0
    automated_accounts: int = 0
    shallow: bool = False
    reason: str | None = None


def status_of(days_since_last_commit: int | None, window_days: int) -> Status:
    """Classify a repository by the days since its last commit.

    Args:
        days_since_last_commit: None for a repository with no commit.
        window_days: The activity window.

    Returns:
        "active" within the window, "quiet" within `QUIET_UNTIL_DAYS`,
        "dormant" beyond, "empty" with no commit.
    """
    if days_since_last_commit is None:
        return "empty"
    if days_since_last_commit < window_days:
        return "active"
    if days_since_last_commit < max(window_days, QUIET_UNTIL_DAYS):
        return "quiet"
    return "dormant"


def describe_repository(
    path: str,
    branch: str | None,
    last_commit: datetime.date | None,
    in_window: list[Commit],
    until: datetime.date,
    window_days: int,
    *,
    shallow: bool,
) -> RepositoryActivity:
    """Build one repository's row from its facts.

    Args:
        path: Relative to the directory searched.
        branch: The checked-out branch.
        last_commit: The last non-merge commit's date, or None with none.
        in_window: The commits in the window.
        until: The window's last day.
        window_days: The window's length.
        shallow: Whether only part of the history is present.

    Returns:
        The row; counts only, no identity.
    """
    days = (until - last_commit).days if last_commit is not None else None
    identities = {(c.author_email.lower(), c.author_name) for c in in_window}
    automated = {email for email, name in identities if is_automated(name, email)}
    people = {email for email, _ in identities} - automated
    return RepositoryActivity(
        path=path,
        status=status_of(days, window_days),
        branch=branch,
        last_commit=last_commit,
        days_since_last_commit=days,
        commits=len(in_window),
        people=len(people),
        automated_accounts=len(automated),
        shallow=shallow,
    )


def status_counts(rows: list[RepositoryActivity]) -> dict[Status, int]:
    """Count the rows by status, every status present, in `STATUSES` order.

    Args:
        rows: The repositories.

    Returns:
        Status to number of repositories.
    """
    counted = Counter(row.status for row in rows)
    return {status: counted.get(status, 0) for status in STATUSES}
