# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`git worktree list --porcelain`, with `-z` (Git 2.36+) and without."""

from __future__ import annotations

import pytest

from reveille.adapters.git_reader import _parse_worktrees
from reveille.domain.state import Worktree

pytestmark = pytest.mark.unit

_MAIN = Worktree(path="/r", branch="main", locked=False, prunable=False)


def test_nul_terminated_records_keep_a_newline_in_a_path() -> None:
    out = (
        "worktree /r\0HEAD 1\0branch refs/heads/main\0\0worktree /w\nlocked x\0detached\0locked\0\0"
    )

    assert _parse_worktrees(out) == [
        _MAIN,
        Worktree(path="/w\nlocked x", branch=None, locked=True, prunable=False),
    ]


def test_newline_records_from_older_git() -> None:
    out = "worktree /r\nHEAD 1\nbranch refs/heads/main\n\nworktree /w\nbranch refs/heads/side\nprunable gone\n"

    assert _parse_worktrees(out, nul=False) == [
        _MAIN,
        Worktree(path="/w", branch="side", locked=False, prunable=True),
    ]


def test_newline_records_keep_a_line_separator_in_a_path() -> None:
    # `splitlines` also ends a line at U+001E, U+0085 and U+2028; Git ends one at "\n".
    out = "worktree /r\nHEAD 1\nbranch refs/heads/main\n\nworktree /w\x1ex\u2028y\x85z\ndetached\n"

    assert _parse_worktrees(out, nul=False) == [
        _MAIN,
        Worktree(path="/w\x1ex\u2028y\x85z", branch=None, locked=False, prunable=False),
    ]


def test_newline_records_keep_a_line_separator_ending_the_last_branch() -> None:
    out = "worktree /r\nHEAD 1\nbranch refs/heads/main\u2028\n\n"

    assert _parse_worktrees(out, nul=False) == [
        Worktree(path="/r", branch="main\u2028", locked=False, prunable=False)
    ]
