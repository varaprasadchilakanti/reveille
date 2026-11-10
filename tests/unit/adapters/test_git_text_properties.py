# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Properties of the parsers that read text Git prints, over generated input.

Each test builds Git's output from parts, the way Git's documentation describes the
format, and checks the parser gives the parts back. A repository can choose every byte
of a path, a branch name or an author name, so the parts are arbitrary text.
"""

from __future__ import annotations

import dataclasses
import datetime

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from reveille.adapters.git_reader import (
    _MAX_EMAIL_LENGTH,
    _MAX_NAME_LENGTH,
    _iter_numstat,
    _Mailmap,
    _parse_log_record,
    _parse_mailmap_line,
    _parse_status,
    _parse_worktrees,
    _strip_invisible,
    _sum_numstat,
    _unquote_path,
)
from reveille.domain.models import Commit
from reveille.domain.state import Worktree

pytestmark = pytest.mark.unit

# Text Git can hold in a path or ref name: anything but NUL.
_NO_NUL = st.text(st.characters(exclude_characters="\0"), min_size=1)
# Text decoded from Git's output: a byte that is not UTF-8 arrives as a lone surrogate.
_FROM_GIT = st.text(st.characters(exclude_categories=()))

# quote.c `cq_lookup`: the C escapes Git writes; any other byte it quotes is octal.
_C_ESCAPES = {7: "a", 8: "b", 9: "t", 10: "n", 11: "v", 12: "f", 13: "r", 34: '"', 92: "\\"}


def _git_quote(path: str) -> str:
    """Quote a path as Git does with `core.quotePath` on: C escapes, octal for the rest."""
    raw = path.encode("utf-8")
    if not any(b < 0x20 or b in (34, 92, 0x7F) or b >= 0x80 for b in raw):
        return path
    out = []
    for b in raw:
        if b in _C_ESCAPES:
            out.append("\\" + _C_ESCAPES[b])
        elif b < 0x20 or b >= 0x7F:
            out.append(f"\\{b:03o}")
        else:
            out.append(chr(b))
    return '"' + "".join(out) + '"'


@given(st.text(min_size=1))
@example('\a\b\t\n\v\f\r"\\').via("each C escape, which random text rarely holds")
def test_a_quoted_path_decodes_to_the_path(path: str) -> None:
    assert _unquote_path(_git_quote(path)) == path


# Random text is rarely shaped like a quoted path; these tokens are.
_QUOTED_SHAPED = st.lists(
    st.sampled_from(["\\", "\\377", "\\303", "\\n", "\\q", "0", "7", '"', "a", "\u00e9"])
).map(lambda parts: '"' + "".join(parts) + '"')


@given(st.one_of(_FROM_GIT, _QUOTED_SHAPED))
def test_unquoting_any_text_never_raises(text: str) -> None:
    assert isinstance(_unquote_path(text), str)


# --- .mailmap ---------------------------------------------------------------

_NAME = st.text(st.characters(exclude_characters="<\0\n"))
_EMAIL = st.text(st.characters(exclude_characters=">\0\n"), min_size=1)


def _stripped(name: str) -> str | None:
    # As `git check-mailmap` trims a name: space, tab, CR and LF, not a vertical tab or form feed.
    return name.strip(" \t\r\n") or None


@given(_NAME, _EMAIL, st.text(st.characters(exclude_characters="<\n")))
def test_a_mailmap_line_with_one_address_maps_that_address(
    name: str, email: str, rest: str
) -> None:
    assume(not name.startswith("#"))

    assert _parse_mailmap_line(f"{name}<{email}>{rest}") == (_stripped(name), None, None, email)


@given(_NAME, _EMAIL, _NAME, st.text(st.characters(exclude_characters=">\0\n")), _FROM_GIT)
def test_a_mailmap_line_with_two_addresses_maps_the_second_to_the_first(
    name: str, email: str, commit_name: str, commit_email: str, rest: str
) -> None:
    assume(not name.startswith("#"))
    line = f"{name}<{email}>{commit_name}<{commit_email}>{rest}"

    assert _parse_mailmap_line(line) == (
        _stripped(name),
        email,
        _stripped(commit_name),
        commit_email,
    )


@given(st.one_of(_FROM_GIT, st.text(st.sampled_from("<> #\ta\x1e\u2028"))))
def test_parsing_any_mailmap_line_never_raises(line: str) -> None:
    _parse_mailmap_line(line)


# --- git status --porcelain=v2 -z -------------------------------------------

_XY = st.text(st.sampled_from(".MTADRCU"), min_size=2, max_size=2)
# A rename's original path is its own field; one that looks like an entry must not be read as one.
_ORIGINAL = st.one_of(_NO_NUL, _NO_NUL.map(lambda p: "? " + p), _NO_NUL.map(lambda p: "1 .M " + p))
_HEADS = "# branch.oid (initial)\0# branch.head main\0"


@given(st.lists(st.tuples(st.sampled_from("12u?"), _XY, _NO_NUL, _ORIGINAL), max_size=6))
def test_status_reads_each_path_whole_and_in_its_categories(
    entries: list[tuple[str, str, str, str]],
) -> None:
    fields = []
    expected: dict[str, list[str]] = {
        k: [] for k in ("staged", "modified", "deleted", "renamed", "untracked", "conflicted")
    }
    for kind, xy, path, original in entries:
        if kind == "?":
            fields.append(f"? {path}")
            expected["untracked"].append(path)
        elif kind == "u":
            fields.append(f"u {xy} N... 100644 100644 100644 100644 a b c {path}")
            expected["conflicted"].append(path)
        else:
            heads = "N... 100644 100644 100644 a b"
            if kind == "2":
                fields += [f"2 {xy} {heads} R100 {path}", original]
                expected["renamed"].append(path)
            else:
                fields.append(f"1 {xy} {heads} {path}")
            if xy[0] != ".":
                expected["staged"].append(path)
            if xy[1] in "MT":
                expected["modified"].append(path)
            if "D" in xy:
                expected["deleted"].append(path)

    status = _parse_status(_HEADS + "".join(f + "\0" for f in fields))

    assert status.branch == "main"
    assert status.head is None
    assert {k: getattr(status, k) for k in expected} == expected


# --- git worktree list --porcelain ------------------------------------------


def _worktrees(text: st.SearchStrategy[str]) -> st.SearchStrategy[Worktree]:
    return st.builds(
        Worktree,
        path=text,
        branch=st.one_of(st.none(), text),
        locked=st.booleans(),
        prunable=st.booleans(),
        bare=st.booleans(),
    )


def _porcelain(tree: Worktree, end: str) -> str:
    lines = [f"worktree {tree.path}"]
    if tree.bare:
        lines.append("bare")
    else:
        lines.append("HEAD " + "0" * 40)
        lines.append(f"branch refs/heads/{tree.branch}" if tree.branch else "detached")
    if tree.locked:
        lines.append("locked")
    if tree.prunable:
        lines.append("prunable gitdir file points to non-existent location")
    return "".join(line + end for line in lines) + end


def _as_listed(tree: Worktree) -> Worktree:
    # Git prints no branch for a bare worktree.
    return dataclasses.replace(tree, branch=None) if tree.bare else tree


@given(st.lists(_worktrees(_NO_NUL), max_size=4))
def test_nul_terminated_worktrees_read_back_whole(trees: list[Worktree]) -> None:
    output = "".join(_porcelain(t, "\0") for t in trees)

    assert _parse_worktrees(output) == [_as_listed(t) for t in trees]


# Without -z (Git before 2.36) a record ends at a newline, so a path cannot hold one.
_LINE = st.text(st.characters(exclude_characters="\0\n"), min_size=1)


@given(st.lists(_worktrees(_LINE), max_size=4))
@example([Worktree(path="0\x1e0", branch=None, locked=False, prunable=False)]).via(
    "found by Hypothesis: splitlines cut a path at U+001E"
)
@example([Worktree(path="/w", branch="b\u2028", locked=False, prunable=False)]).via(
    "found by Hypothesis: strip took U+2028 from the last branch name"
)
def test_newline_separated_worktrees_read_back_whole(trees: list[Worktree]) -> None:
    output = "".join(_porcelain(t, "\n") for t in trees)

    assert _parse_worktrees(output, nul=False) == [_as_listed(t) for t in trees]


# --- git log records ----------------------------------------------------------

_SHA = "a" * 40
_CONTROL = {*range(0x20), *range(0x7F, 0xA0)}
_HIDDEN = {*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200B, 0xFEFF}


def _record(name: str, email: str, seconds: int, numstat: str = "") -> str:
    return "\x1f".join((_SHA, name, email, str(seconds), _SHA)) + "\n" + numstat


# Random text rarely holds these: a bidi override, zero-width space, BOM, ESC, a C1
# control, the field separator, and an undecodable byte.
_HOSTILE = st.one_of(
    _FROM_GIT,
    st.text(
        st.sampled_from(
            ["a", " ", "\u202e", "\u2066", "\u200b", "\ufeff", "\x1b", "\x85", "\x1f", "\udcff"]
        )
    ),
)


def _parsed(name: str, email: str, proper: str = "") -> list[Commit]:
    """The commits read from a record, and from one whose .mailmap gives `proper` as its name."""
    # A .mailmap is as untrusted as the commit: its proper name is scrubbed too.
    mailmap = _Mailmap(by_email={"x@example.com": (proper or None, "x@example.com")})
    records = (_record(name, email, 0), _record(name, "x@example.com", 0))
    commits = (_parse_log_record(r, mailmap, set(), {_SHA: _SHA}, set()) for r in records)
    return [c for c in commits if c is not None]


@given(_HOSTILE, _HOSTILE, _HOSTILE)
@example("\u200b", "\u202eev@e.test", "").via(
    "found by Hypothesis: an address standing in for an empty name kept a bidi override"
)
def test_a_log_record_never_shows_a_control_or_hidden_character(
    name: str, email: str, proper: str
) -> None:
    for commit in _parsed(name, email, proper):
        shown = commit.author_name + commit.author_email
        assert not {ord(c) for c in shown} & _CONTROL
        assert not {ord(c) for c in commit.author_name} & _HIDDEN
        assert not any(0xD800 <= ord(c) <= 0xDFFF for c in shown)


@given(_FROM_GIT, _FROM_GIT)
@example("", "a" * 300).via("an address standing in for a name is cut as an address")
@example("n" * 300, "e" * 400).via("each field over its limit, which random text rarely is")
@example("", "a" * 150 + "\u200b" + "a" * 150).via("a long address with a hidden character")
def test_a_log_record_bounds_the_name_and_address_it_shows(name: str, email: str) -> None:
    for commit in _parsed(name, email):
        assert len(commit.author_email) <= _MAX_EMAIL_LENGTH + 1
        # The name is cut at its own limit, or is the address standing in for it.
        assert len(commit.author_name) <= _MAX_NAME_LENGTH + 1 or (
            commit.author_name == _strip_invisible(commit.author_email)
        )


_PLAIN = st.text(st.characters(min_codepoint=0x20, max_codepoint=0x7E), min_size=1, max_size=50)


@given(_PLAIN.filter(lambda s: s.strip() == s), _PLAIN, st.integers(0, 4_102_444_800))
def test_a_plain_log_record_keeps_its_author(name: str, email: str, seconds: int) -> None:
    commit = _parse_log_record(
        _record(name, email, seconds), _Mailmap(), set(), {_SHA: _SHA}, set()
    )

    assert commit is not None
    assert (commit.author_name, commit.author_email) == (name, email)
    assert commit.timestamp == datetime.datetime.fromtimestamp(seconds, datetime.UTC)


_COUNT = st.one_of(st.integers(0, 10**6), st.just(-1))  # -1 stands for a binary file's "-"


@given(st.lists(st.tuples(_COUNT, _COUNT, _NO_NUL.filter(lambda p: "\n" not in p))))
def test_numstat_totals_are_the_sum_of_the_text_lines(rows: list[tuple[int, int, str]]) -> None:
    def shown(n: int) -> str:
        return "-" if n < 0 else str(n)

    block = "".join(f"{shown(a)}\t{shown(d)}\t{p}\n" for a, d, p in rows)

    assert _sum_numstat(block) == (
        sum(max(a, 0) for a, _, _ in rows),
        sum(max(d, 0) for _, d, _ in rows),
    )


# A path that holds "=>" reads as a rename: Git prints a rename and such a path alike without -z.
_NUMSTAT_PATH = st.text(
    st.characters(exclude_characters="\0", exclude_categories=("Cs",)), min_size=1
).filter(lambda p: "=>" not in p)


@given(st.lists(st.tuples(st.integers(0, 10**6), st.integers(0, 10**6), _NUMSTAT_PATH)))
@(
    example([(1, 0, "a => b")])
    .via("the known limit: a path holding ' => ' is read as a rename")
    .xfail()
)
def test_numstat_rows_read_back_as_git_quotes_their_paths(rows: list[tuple[int, int, str]]) -> None:
    block = "".join(f"{a}\t{d}\t{_git_quote(p)}\n" for a, d, p in rows)

    assert list(_iter_numstat(block)) == [(p, a, d) for a, d, p in rows]
