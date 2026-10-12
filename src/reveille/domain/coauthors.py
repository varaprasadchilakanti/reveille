# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Co-authorship stated beside authorship, never added to it (ADR 0014).

Counting a commit per identity would stop the charts adding up. A trailer is
an unverified claim: "credited", not "wrote".
"""

from __future__ import annotations

from collections import defaultdict

from reveille.domain.models import CoAuthor, Commit


def co_authors_only(commits: list[Commit]) -> list[CoAuthor]:
    """Return the identities credited only as co-authors, alphabetically.

    Args:
        commits: The commits in the window, with their co-authors attached.

    Returns:
        One entry per identity that only co-authored, ordered by name, never
        by count (which would make it a ranking).
    """
    authors = {c.author_email.lower() for c in commits}
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for commit in commits:
        for name, email in commit.co_authors:
            if email in authors:
                continue
            counts[email] += 1
            names[email] = name
    return sorted(
        (CoAuthor(name=names[e], email=e, co_authored_commits=n) for e, n in counts.items()),
        key=lambda c: (c.name.casefold(), c.email),
    )


def commits_with_co_authors(commits: list[Commit]) -> int:
    """Return how many commits credit at least one co-author.

    Args:
        commits: The commits in the window.

    Returns:
        The count.
    """
    return sum(1 for c in commits if c.co_authors)
