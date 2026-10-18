# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Replace every email address in a report with a token that means nothing outside it.

For a report that is shared: an address is the likeliest thing in it to be
misused, and names alone still let a reader tell people apart. A token is
numbered in the order people are listed, not derived from the address, so it
cannot be reversed by hashing a guessed address. The `.invalid` top-level
domain (RFC 2606) can never receive mail.

Every figure is unchanged: each address maps to exactly one token, and an
automated account keeps the `[bot]` marker it is recognised by.
"""

from __future__ import annotations

import re
from dataclasses import replace

from reveille.domain.areas import is_automated
from reveille.domain.models import (
    AreaActivity,
    CoAuthor,
    Commit,
    ContributorStats,
    RankedContributor,
    ReportData,
)

#: The domain every token carries; a reader of the code can tell a token from an address.
HIDDEN_DOMAIN = "hidden.invalid"

# An address written into a display name, as some Git configurations produce.
# Square brackets end it, so a `[bot]` suffix after an address survives.
_ADDRESS_IN_TEXT = re.compile(r"[^\s<>@\[\]]+@[^\s<>@\[\]]+")

# The user part of a remote, scp-like (`user@host:path`) or a URL (`ssh://user@host/path`).
_USER_IN_REMOTE = re.compile(r"^((?:[a-z][a-z0-9+.-]*://)?)[^@/:]+@")


def hide_emails(data: ReportData) -> ReportData:
    """Return the report with every address replaced by a per-report token.

    Args:
        data: The report as computed.

    Returns:
        The same report, with tokens for addresses and for addresses inside names.
    """
    tokens = _Tokens()
    # Numbered in table order, so the numbering says nothing the table does not.
    for ranked in data.ranked_contributors:
        tokens.of(ranked.stats.email, ranked.stats.name)
    for stats in data.suppressed_contributors:
        tokens.of(stats.email, stats.name)
    for co_author in data.co_authors_only:
        tokens.of(co_author.email, co_author.name)
    for commit in sorted(data.commits, key=lambda c: (c.timestamp, c.sha)):
        tokens.of(commit.author_email, commit.author_name)
        for name, email in commit.co_authors:
            tokens.of(email, name)

    remote = data.metadata.remote_url
    return replace(
        data,
        # An SSH remote can carry a person's login: `jane@host:group/repo`.
        metadata=replace(
            data.metadata, remote_url=_USER_IN_REMOTE.sub(r"\1", remote) if remote else remote
        ),
        ranked_contributors=[_ranked(r, tokens) for r in data.ranked_contributors],
        suppressed_contributors=[_stats(s, tokens) for s in data.suppressed_contributors],
        commits=[_commit(c, tokens) for c in data.commits],
        areas=[_area(a, tokens) for a in data.areas],
        co_authors_only=[_co_author(c, tokens) for c in data.co_authors_only],
        provenance=replace(data.provenance, emails_hidden=True),
    )


class _Tokens:
    """Hands out one token per address, in the order addresses are first seen."""

    def __init__(self) -> None:
        self._by_address: dict[str, str] = {}

    def of(self, email: str, name: str) -> str:
        """Return the token for `email`, assigning the next one if it is new.

        Args:
            email: The address; compared lower-cased, as identities are.
            name: The display name, which decides whether the token keeps `[bot]`.

        Returns:
            The token.
        """
        key = email.lower()
        token = self._by_address.get(key)
        if token is None:
            number = len(self._by_address) + 1
            marker = "[bot]" if is_automated(name, email) else ""
            token = f"contributor-{number}{marker}@{HIDDEN_DOMAIN}"
            self._by_address[key] = token
        return token

    def name(self, name: str) -> str:
        """Return a display name with any address written into it removed.

        Args:
            name: The display name.

        Returns:
            The name, each address in it replaced by "(address hidden)".
        """
        return _ADDRESS_IN_TEXT.sub("(address hidden)", name)


def _stats(stats: ContributorStats, tokens: _Tokens) -> ContributorStats:
    return replace(stats, email=tokens.of(stats.email, stats.name), name=tokens.name(stats.name))


def _ranked(ranked: RankedContributor, tokens: _Tokens) -> RankedContributor:
    return replace(ranked, stats=_stats(ranked.stats, tokens))


def _commit(commit: Commit, tokens: _Tokens) -> Commit:
    return replace(
        commit,
        author_email=tokens.of(commit.author_email, commit.author_name),
        author_name=tokens.name(commit.author_name),
        co_authors=tuple(
            (tokens.name(name), tokens.of(email, name)) for name, email in commit.co_authors
        ),
    )


def _area(area: AreaActivity, tokens: _Tokens) -> AreaActivity:
    # Every address here is a commit author's, so each already has its token.
    return replace(area, authors={tokens.of(email, ""): day for email, day in area.authors.items()})


def _co_author(co_author: CoAuthor, tokens: _Tokens) -> CoAuthor:
    return replace(
        co_author,
        email=tokens.of(co_author.email, co_author.name),
        name=tokens.name(co_author.name),
    )
