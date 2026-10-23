# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Every line `state` and `brief` can print, in every format, with exact wording.

The integration tests build real repositories, which rarely have everything at
once: an upstream, a merge in progress, conflicts, other worktrees, a tag, a
shallow clone, filters not run. Here one state and one brief carry all of it.
"""

from __future__ import annotations

import dataclasses
import datetime
import json

import pytest

from reveille.adapters.renderer import Renderer
from reveille.domain.brief import Brief
from reveille.domain.state import RepositoryState, Worktree

pytestmark = pytest.mark.unit

_FULL = RepositoryState(
    branch="main",
    head="1234567890abcdef",
    upstream="origin/main",
    ahead=2,
    behind=3,
    operation="merge",
    conflicted=("c.txt",),
    staged=("s.txt",),
    modified=("m.txt",),
    deleted=(),
    renamed=(),
    untracked=("u.txt",),
    stashes=2,
    worktrees=(
        Worktree(path="/r", branch="main", locked=False, prunable=False, current=True),
        Worktree(path="/w", branch=None, locked=True, prunable=False),
    ),
    branches=4,
    branches_merged=1,
    branches_quiet=2,
    latest_tag="v1.0",
    commits_since_tag=5,
    last_commit=datetime.date(2026, 3, 1),
    bare=False,
    shallow=True,
    filters_not_run=("lfs",),
)


def _state(fmt: str) -> str:
    return Renderer.state_text(_FULL, name="r", history_replaced=True, output_format=fmt, limit=10)


def test_state_text_states_everything() -> None:
    lines = _state("text").splitlines()

    assert lines[:4] == [
        "r: on main (1234567, 2026-03-01).",
        "Tracking origin/main: 2 ahead, 3 behind, as of the last fetch.",
        "In progress: merge.",
        "Conflicted: c.txt.",
    ]
    assert "2 stashes; 1 other worktree: /w (detached)." in lines
    assert (
        "Branches: 4 local, 1 merged into this commit, 2 with no commit in 90 days before it."
        in lines
    )
    assert "Latest tag: v1.0, 5 commits since. Next: reveille brief --from v1.0" in lines
    assert "Shallow clone: only part of the history is present." in lines
    assert "Replace refs or a graft file are present and not followed." in lines
    assert any(
        line.startswith("Not run: the content filters") and "(lfs)" in line for line in lines
    )


def test_state_markdown_states_everything() -> None:
    out = _state("markdown")

    for expected in (
        "- **Branch:** `main` at `1234567` (2026-03-01)",
        "- **Upstream:** `origin/main`, 2 ahead, 3 behind, as of the last fetch",
        "- **In progress:** merge",
        "- **Conflicted:** `c.txt`",
        "  - Staged: `s.txt`",
        "- **Stashes:** 2",
        "- **Other worktrees:** `/w (detached)`",
        "- **Latest tag:** `v1.0`, 5 commits since",
        "- **Not run:** content filters",
        "- Shallow clone: only part of the history is present.",
        "- Replace refs or a graft file are present and not followed.",
    ):
        assert expected in out, expected


@pytest.mark.parametrize("fmt", ["text", "markdown"])
def test_state_counts_one_commit_in_the_singular(fmt: str) -> None:
    state = dataclasses.replace(_FULL, commits_since_tag=1)

    out = Renderer.state_text(state, name="r", history_replaced=False, output_format=fmt, limit=10)

    assert "1 commit since" in out


@pytest.mark.parametrize("fmt", ["text", "markdown"])
def test_state_names_a_dash_tag_by_its_full_ref_so_the_suggestion_runs(fmt: str) -> None:
    state = dataclasses.replace(_FULL, latest_tag="-v1")

    out = Renderer.state_text(state, name="r", history_replaced=False, output_format=fmt, limit=10)

    assert "reveille brief --from refs/tags/-v1" in out


def test_state_line_states_everything() -> None:
    assert _state("line") == (
        "r: main 1234567; 2 ahead, 3 behind; merge in progress; "
        "1 conflicted, 1 staged, 1 modified, 1 untracked; 2 stashes; v1.0 +5; "
        "1 filter not run; shallow\n"
    )


def test_state_json_keeps_the_upstream_and_worktrees() -> None:
    document = json.loads(_state("json"))

    assert document["upstream"] == {
        "name": "origin/main",
        "ahead": 2,
        "behind": 3,
        "as_of": "last fetch",
    }
    assert document["operation_in_progress"] == "merge"
    assert document["worktrees"][1] == {
        "path": "/w",
        "branch": None,
        "locked": True,
        "prunable": False,
        "current": False,
        "bare": False,
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"bare": True}, "r: main 1234567; bare\n"),
        ({"working_tree_unread": True}, "r: main 1234567; working tree not compared\n"),
        ({"branch": None, "head": None}, "r: detached, no commits yet; clean\n"),
    ],
)
def test_state_line_for_unusual_trees(changes: dict[str, object], expected: str) -> None:
    plain = dict(
        _FULL.__dict__,
        upstream=None,
        operation=None,
        conflicted=(),
        staged=(),
        modified=(),
        untracked=(),
        stashes=0,
        latest_tag=None,
        shallow=False,
        filters_not_run=(),
    )
    state = RepositoryState(**{**plain, **changes})

    assert (
        Renderer.state_text(state, name="r", history_replaced=False, output_format="line", limit=10)
        == expected
    )


_BRIEF = Brief(
    commits=3,
    people=2,
    automated=1,
    co_authored=1,
    first=datetime.date(2026, 3, 1),
    last=datetime.date(2026, 3, 3),
    areas=(("src/core", 2),),
    file_types=((".py", 2),),
    files_added=1,
    active_again=("docs",),
)


def _brief(fmt: str) -> str:
    return Renderer.brief_text(
        _BRIEF,
        repository=("r", "main"),
        point=("v1.0", "abcdef1234567890"),
        tip="fedcba9876543210",
        tags=["v1.1"],
        output_format=fmt,
        limit=5,
    )


def test_brief_text_states_everything() -> None:
    out = _brief("text")

    assert "3 commits by 2 people and 1 automated account" in out
    assert "Active again after 90 or more quiet days: docs." in out
    assert "Tags in the range: v1.1." in out
    assert "Next: reveille brief --from fedcba987654" in out


def test_brief_markdown_states_everything() -> None:
    out = _brief("markdown")

    assert "- **Active again after 90 quiet days:** `docs`" in out
    assert "- **Tags in the range:** `v1.1`" in out


def test_brief_line_states_everything() -> None:
    assert _brief("line") == (
        "r main since v1.0 to fedcba9: 3 commits by 2 people, 1 automated account, "
        "1 file added, 1 tag\n"
    )


def test_state_markdown_for_a_detached_head_before_any_commit() -> None:
    state = RepositoryState(**{**_FULL.__dict__, "branch": None, "head": None, "last_commit": None})

    out = Renderer.state_text(
        state, name="r", history_replaced=False, output_format="markdown", limit=10
    )

    assert "- **Branch:** detached, no commits yet" in out


def test_an_empty_name_is_shown_not_dropped() -> None:
    from reveille.adapters.renderer import _md

    assert _md("") == "(empty)"


def test_state_lists_the_worktrees_other_than_the_one_marked_current() -> None:
    main, linked = _FULL.worktrees
    worktrees = (
        dataclasses.replace(main, current=False),
        dataclasses.replace(linked, current=True),
    )
    state = dataclasses.replace(_FULL, worktrees=worktrees)

    text = Renderer.state_text(
        state, name="r", history_replaced=False, output_format="text", limit=9
    )

    assert "2 stashes; 1 other worktree: /r (main)." in text.splitlines()


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [("text", "2 stashes; 2 worktrees: /r (main), /w (detached)."), ("markdown", "**Worktrees:**")],
)
def test_when_the_worktree_read_is_not_known_none_is_called_other(fmt: str, expected: str) -> None:
    """It was taken to be the first: from a moved worktree, the main one was "other"."""
    main, linked = _FULL.worktrees
    state = dataclasses.replace(_FULL, worktrees=(dataclasses.replace(main, current=False), linked))

    out = Renderer.state_text(state, name="r", history_replaced=False, output_format=fmt, limit=9)

    assert expected in out
    assert "other worktree" not in out.casefold()
