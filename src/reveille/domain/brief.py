# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""What changed between a point and the analysed branch, in counts (ADR 0022).

Names nobody and measures no period: no Gini, concentration or quiet run,
which mislead over a short range. People and automated accounts are counted
apart, as in the distribution figures (ADR 0017).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass

from reveille.domain.areas import is_automated
from reveille.domain.coauthors import commits_with_co_authors
from reveille.domain.files import file_type
from reveille.domain.models import AreaActivity, Commit, FileStats

#: Days without a commit before an area counts as active again.
QUIET_DAYS = 90


@dataclass(frozen=True)
class Brief:
    """The facts a brief states.

    Attributes:
        commits: Non-merge commits in the range.
        people: Distinct people who authored them.
        automated: Distinct automated accounts that authored them.
        co_authored: Commits crediting a co-author.
        first: Date of the earliest commit in the range.
        last: Date of the latest commit in the range.
        areas: `(area, commits)`, most commits first, then by name.
        file_types: `(type, file changes)`, most first, then by name.
        files_added: Files added in the range.
        active_again: Areas changed in the range after `QUIET_DAYS` or more without a commit.
    """

    commits: int
    people: int
    automated: int
    co_authored: int
    first: datetime.date
    last: datetime.date
    areas: tuple[tuple[str, int], ...]
    file_types: tuple[tuple[str, int], ...]
    files_added: int
    active_again: tuple[str, ...]


def describe_range(
    commits: list[Commit],
    files: list[FileStats],
    areas: list[AreaActivity],
    files_added: int,
    previous_change: dict[str, datetime.date | None],
) -> Brief:
    """Count what changed in a range of commits.

    Args:
        commits: The range's commits, merges and exclusions already removed.
        files: Per-path commit counts in the range.
        areas: Per-area activity in the range.
        files_added: Files added in the range.
        previous_change: Each area's last change before the range, None if it had none.

    Returns:
        The brief's facts.

    Raises:
        ValueError: If `commits` is empty; an empty range is a negative answer.
    """
    if not commits:
        raise ValueError("a brief needs at least one commit")
    identities = {(c.author_email.lower(), c.author_name) for c in commits}
    automated = {email for email, name in identities if is_automated(name, email)}
    people = {email for email, _ in identities} - automated

    types: dict[str, int] = defaultdict(int)
    for stats in files:
        types[file_type(stats.path)] += stats.commits

    first_by_area = {a.area: a.first_changed or a.last_changed for a in areas}
    active_again = sorted(
        area
        for area, before in previous_change.items()
        if before is not None
        and area in first_by_area
        and (first_by_area[area] - before).days >= QUIET_DAYS
    )
    dates = [c.timestamp.date() for c in commits]
    return Brief(
        commits=len(commits),
        people=len(people),
        automated=len(automated),
        co_authored=commits_with_co_authors(commits),
        first=min(dates),
        last=max(dates),
        areas=tuple(sorted(((a.area, a.commits) for a in areas), key=lambda x: (-x[1], x[0]))),
        file_types=tuple(sorted(types.items(), key=lambda x: (-x[1], x[0]))),
        files_added=files_added,
        active_again=tuple(active_again),
    )
