# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Every Git command the reader runs goes through `GitReader._git()`, which pins settings.

A call made with `self._repo.git.<command>` skips the `-c` pins that keep a
repository's config from starting fsmonitor or a signature program.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import reveille.adapters.git_reader as git_reader

pytestmark = pytest.mark.unit


def _direct_git_calls(source: str) -> list[str]:
    """Name each `self._repo.git` use outside `_git`, other than setting the environment."""
    tree = ast.parse(source)
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef) or function.name == "_git":
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "git"
                and isinstance(node.value.value, ast.Attribute)
                and node.value.value.attr == "_repo"
                and node.attr != "update_environment"
            ):
                found.append(f"{function.name}: .git.{node.attr}")
    return found


def test_no_git_command_skips_the_pinned_runner() -> None:
    source = Path(git_reader.__file__).read_text(encoding="utf-8")

    assert _direct_git_calls(source) == []


def test_the_check_finds_a_direct_call() -> None:
    sample = "class R:\n    def f(self):\n        return self._repo.git.rev_parse('--git-dir')\n"

    assert _direct_git_calls(sample) == ["f: .git.rev_parse"]
