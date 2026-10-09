# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Who changed each area of a repository, stated by fixed rules (ADR 0013).

The question this answers is "who has worked on this part of the code?",
asked per directory rather than per person. Each statement describes an
area: how many commits changed it, how many authors made them, who they
are, and when it was last changed. People appear only as the list of those
who touched it.

What it deliberately does not do:

* describe a person. There is no "mainly", "owner" or "expert", no count
  or share of an area per person, and no lookup from a person to areas;
* order people. Names are alphabetical, and the only date printed belongs
  to the area. Newest-first with a date per name would be a recency
  ranking, and a person's last date reads as a departure date. When there
  are more than five names, the five shown are those who changed the area
  most recently -- the useful five for "whom do I ask?" -- and the line
  says that is how they were chosen;
* claim knowledge. Commits say where someone's work landed in a window,
  not what they know: that needs blame and review history, neither of
  which Reveille reads (ADR 0005).

Like the findings, every statement is a rule over numbers that appear in
the report, with no model and no network, and the same history always
produces the same sentences. Unlike the findings, these name people, which
is why the section exists only when `--area-authors` asks for it.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from reveille.domain.models import AreaActivity, Commit

#: The area files at the top level of a repository belong to.
ROOT_AREA = "(root)"

#: Areas shown, most-changed first. Chosen by commits: by lines would bring
#: back generated churn, by author count would select for the name lists.
_AREAS_SHOWN = 8

#: Names listed per area before the rest are counted as "and N others".
_NAMES_SHOWN = 5

#: Days without a change, before the end of the window, worth stating. The
#: same threshold as the dormancy finding.
_QUIET_DAYS = 30


@dataclass(frozen=True)
class AreaStatement:
    """What the report says about one area.

    The facts first, then the sentences made from them, so the HTML and the
    JSON cannot say different things.

    Attributes:
        area: The directory.
        commits: Commits that changed the area.
        author_count: Authors who are not automated accounts.
        automated_count: Automated accounts.
        named: `(name, address)` of each listed author, alphabetically.
        automated_named: `(name, address)` of each listed automated account.
        not_listed: Identities below `--min-commits`, counted and not named.
        last_changed: When the area was last changed.
        headline: Commits and authors, in one sentence.
        authors: The listed authors, alphabetically, and how many are not
            listed. Empty when every author is automated.
        automated: The automated identities, or an empty string.
        notes: Qualified statements that apply to this area.
        evidence: The date the area was last changed, for display.
    """

    area: str
    commits: int
    author_count: int
    automated_count: int
    named: tuple[tuple[str, str], ...]
    automated_named: tuple[tuple[str, str], ...]
    not_listed: int
    last_changed: datetime.date
    headline: str
    authors: str
    automated: str
    notes: tuple[str, ...]
    evidence: str


def area_of(path: str, depth: int) -> str:
    """Return the area a path belongs to: its directory, cut to `depth`.

    Args:
        path: A repository-relative file path.
        depth: The most directory components an area may have.

    Returns:
        The directory, at most `depth` components long, or ROOT_AREA for a
        file at the top level.
    """
    directories = path.split("/")[:-1]
    if not directories:
        return ROOT_AREA
    return "/".join(directories[:depth])


def is_automated(name: str, email: str) -> bool:
    """Return whether an identity is an automated account.

    A fixed, stated rule rather than a guess: a name or address carrying
    the `[bot]` suffix that GitHub, GitLab and Bitbucket apps use.

    Args:
        name: The identity's display name.
        email: The identity's address.

    Returns:
        True for a `[bot]` identity.
    """
    return name.lower().endswith("[bot]") or "[bot]@" in email.lower()


def describe_areas(
    areas: list[AreaActivity],
    names: dict[str, str],
    listed: set[str],
    window_end: datetime.date,
) -> list[AreaStatement]:
    """Describe the most-changed areas, most commits first.

    Args:
        areas: Activity per area for the analysis window.
        names: Display name for every author address in the window.
        listed: Addresses the report lists. An author below `--min-commits`
            is counted and not named (ADR 0011).
        window_end: The end of the analysis window, against which an area's
            quiet spell is measured, so deterministic output stays so.

    Returns:
        One statement per area shown.
    """
    chosen = sorted(areas, key=lambda a: (-a.commits, a.area))[:_AREAS_SHOWN]
    # A one-author area is worth saying only where other areas have more:
    # in a one-person repository it would repeat under every area.
    people_in_repository = sum(1 for e, n in names.items() if not is_automated(n, e))
    return [
        _describe(area, names, listed, window_end, qualify_single=people_in_repository > 1)
        for area in chosen
    ]


def _describe(
    activity: AreaActivity,
    names: dict[str, str],
    listed: set[str],
    window_end: datetime.date,
    *,
    qualify_single: bool,
) -> AreaStatement:
    """Describe one area."""

    def name_of(address: str) -> str:
        return names.get(address, address)

    automated = sorted(
        (e for e in activity.authors if is_automated(name_of(e), e)),
        key=lambda e: name_of(e).casefold(),
    )
    people = [e for e in activity.authors if e not in automated]

    counted = [_count(len(people), "author")] if people else []
    if automated:
        counted.append(_count(len(automated), "automated account"))
    headline = f"{_count(activity.commits, 'commit')} by {' and '.join(counted)}."

    named = sorted(
        ((names.get(e, e), e) for e in people if e in listed), key=lambda n: n[0].casefold()
    )
    bots = [(names.get(e, e), e) for e in automated if e in listed]
    # Anybody below the threshold, person or automation, is counted and not
    # named, and the line says how many (ADR 0011).
    unlisted = len(people) - len(named) + len(automated) - len(bots)
    authors = _people_line(named, activity.authors, every="Authors", some="Authors include")
    if unlisted:
        held = f"{unlisted:,} below --min-commits {'is' if unlisted == 1 else 'are'} not named."
        authors = f"{authors} {held}".strip()

    automated_line = _people_line(
        sorted(bots, key=lambda n: n[0].casefold()),
        activity.authors,
        every="Automated",
        some="Automated accounts include",
    )

    notes: list[str] = []
    if len(people) == 1 and qualify_single:
        notes.append(
            "Every commit by a person here came from one author. One committer is "
            "not one maintainer: review and pairing do not appear in commit history."
        )
    idle = (window_end - activity.last_changed).days
    if idle >= _QUIET_DAYS:
        notes.append(f"Not changed in the last {_count(idle, 'day')} of the window.")

    return AreaStatement(
        area=activity.area,
        commits=activity.commits,
        author_count=len(people),
        automated_count=len(automated),
        named=tuple(named),
        automated_named=tuple(bots),
        not_listed=unlisted,
        last_changed=activity.last_changed,
        headline=headline,
        authors=authors,
        automated=automated_line,
        notes=tuple(notes),
        evidence=f"last changed {activity.last_changed.isoformat()}",
    )


def _people_line(
    named: list[tuple[str, str]],
    last: dict[str, datetime.date],
    *,
    every: str,
    some: str,
) -> str:
    """List identities: all of them, or the five most recent of many.

    One rule for authors and automated accounts alike: alphabetical, and
    of more than five, the five that changed the area most recently, said so.

    Args:
        named: `(name, address)` of each identity, alphabetically.
        last: When each address last changed the area.
        every: The label when every identity is listed.
        some: The label when only the most recent five are.

    Returns:
        The line, or an empty string when nobody is listed.
    """
    if not named:
        return ""
    if len(named) <= _NAMES_SHOWN:
        return f"{every}: {_name_list([name for name, _ in named])}"
    recent = sorted(named, key=lambda n: (-last[n[1]].toordinal(), n[1]))[:_NAMES_SHOWN]
    shown = sorted((name for name, _ in recent), key=str.casefold)
    rest = len(named) - len(shown)
    return (
        f"{some} {', '.join(shown[:-1])} and {shown[-1]}, the five to change "
        f"it most recently, and {_count(rest, 'other')}."
    )


def _name_list(names: list[str]) -> str:
    """Join names alphabetically ordered by the caller, five at most."""
    if not names:
        return ""
    shown = names[:_NAMES_SHOWN]
    rest = len(names) - len(shown)
    if rest:
        return f"{', '.join(shown)} and {_count(rest, 'other')}."
    if len(shown) == 1:
        return f"{shown[0]}."
    return f"{', '.join(shown[:-1])} and {shown[-1]}."


def _count(n: int, singular: str) -> str:
    """Return "1 thing" or "N things"."""
    return f"{n:,} {singular}" if n == 1 else f"{n:,} {singular}s"


@dataclass(frozen=True)
class PathAnswer:
    """Who changed one path in the window: `reveille who-changed` (ADR 0015).

    The rules of ADR 0013 applied to a single path: authors alphabetically,
    automated accounts apart, one date for the path, and no count or date
    for any person.

    Attributes:
        path: The path asked about, as given.
        commits: Commits that changed it.
        last_changed: When it was last changed.
        authors: `(name, address)` of every author, alphabetically.
        recently_active: `(name, address)` of the five authors who changed it
            most recently, alphabetically -- whom to ask first.
        automated: `(name, address)` of automated accounts, alphabetically.
        co_authored_commits: Of those commits, how many credit a co-author.
        co_authors: `(name, address)` of co-authors who did not also author a
            commit here, alphabetically.
    """

    path: str
    commits: int
    last_changed: datetime.date
    authors: tuple[tuple[str, str], ...]
    recently_active: tuple[tuple[str, str], ...]
    automated: tuple[tuple[str, str], ...]
    co_authored_commits: int
    co_authors: tuple[tuple[str, str], ...]


def who_changed(path: str, commits: list[Commit]) -> PathAnswer:
    """State who changed a path, from the commits that changed it.

    Args:
        path: The path asked about.
        commits: The commits that changed it; at least one.

    Returns:
        The answer.
    """
    names: dict[str, str] = {}
    last: dict[str, datetime.date] = {}
    for commit in sorted(commits, key=lambda c: c.timestamp):
        email = commit.author_email.lower()
        names[email] = commit.author_name
        last[email] = commit.timestamp.date()

    def by_name(identities: list[str]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(((names[e], e) for e in identities), key=lambda n: n[0].casefold()))

    automated = [e for e in names if is_automated(names[e], e)]
    people = [e for e in names if e not in automated]
    recent = sorted(people, key=lambda e: (-last[e].toordinal(), e))[:_NAMES_SHOWN]

    credited: dict[str, str] = {}
    for commit in commits:
        for name, email in commit.co_authors:
            if email not in names:
                credited.setdefault(email, name)

    return PathAnswer(
        path=path,
        commits=len(commits),
        last_changed=max(last.values()),
        authors=by_name(people),
        recently_active=by_name(recent),
        automated=by_name(automated),
        co_authored_commits=sum(1 for c in commits if c.co_authors),
        co_authors=tuple(
            sorted(((n, e) for e, n in credited.items()), key=lambda n: n[0].casefold())
        ),
    )
