# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A repository's present state: branch, work in progress, working tree (ADR 0024).

Names nobody: no author, and no branch names beyond the current one and the
worktrees'. Branches are counted, never listed.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

#: Days without a commit before a branch counts as quiet.
QUIET_BRANCH_DAYS = 90


@dataclass(frozen=True)
class Worktree:
    """One working tree attached to the repository.

    Attributes:
        path: Its directory, as Git records it.
        branch: The branch checked out there, or None if detached or bare.
        locked: Whether it is locked against pruning.
        prunable: Whether Git would prune it (its directory is gone).
    """

    path: str
    branch: str | None
    locked: bool
    prunable: bool


@dataclass(frozen=True)
class RepositoryState:
    """What `reveille state` reports.

    Attributes:
        branch: The current branch, or None when detached or unborn.
        head: The current commit, or None before the first commit.
        upstream: The branch's upstream, as configured.
        ahead: Commits on the branch not on the upstream, as of the last fetch.
        behind: Commits on the upstream not on the branch, as of the last fetch.
        operation: "merge", "rebase", "am", "cherry-pick", "revert" or "bisect" in progress.
        conflicted: Paths with unresolved conflicts.
        staged: Paths with changes staged for the next commit.
        modified: Paths changed in the working tree and not staged.
        deleted: Paths deleted, staged or not.
        renamed: Paths staged as renamed, under their new name.
        untracked: Untracked paths (directories collapsed, as Git shows them).
        stashes: Stash entries.
        worktrees: Every working tree, the main one first.
        branches: Local branches.
        branches_merged: Local branches whose tip the current commit contains.
        branches_quiet: Local branches with no commit in `QUIET_BRANCH_DAYS` before the current one.
        latest_tag: The nearest tag reachable from the current commit.
        commits_since_tag: Non-merge commits after that tag.
        last_commit: Date of the current commit.
        bare: Whether the repository has no working tree.
        shallow: Whether only part of the history is present.
        filters_not_run: Content filters the repository's own config names, which
            status was computed without; files they cover may show as modified.
        working_tree_unread: Whether the working tree was not compared, because
            Git could not say which config defines its filters.
    """

    branch: str | None
    head: str | None
    upstream: str | None
    ahead: int | None
    behind: int | None
    operation: str | None
    conflicted: tuple[str, ...]
    staged: tuple[str, ...]
    modified: tuple[str, ...]
    deleted: tuple[str, ...]
    renamed: tuple[str, ...]
    untracked: tuple[str, ...]
    stashes: int
    worktrees: tuple[Worktree, ...]
    branches: int
    branches_merged: int
    branches_quiet: int
    latest_tag: str | None
    commits_since_tag: int | None
    last_commit: datetime.date | None
    bare: bool
    shallow: bool
    filters_not_run: tuple[str, ...] = ()
    working_tree_unread: bool = False

    @property
    def clean(self) -> bool:
        """Whether nothing is staged, modified, deleted, renamed, untracked or in conflict."""
        return not (
            self.conflicted
            or self.staged
            or self.modified
            or self.deleted
            or self.renamed
            or self.untracked
        )


def quiet_branches(tips: list[datetime.datetime], reference: datetime.datetime | None) -> int:
    """Count branches whose last commit is `QUIET_BRANCH_DAYS` or more before the reference.

    Measured from the current commit, not the clock, so the count depends on the
    repository alone.

    Args:
        tips: Each local branch's last commit time.
        reference: The current commit's time; None counts nothing.

    Returns:
        How many branches are quiet.
    """
    if reference is None:
        return 0
    return sum((reference - tip).days >= QUIET_BRANCH_DAYS for tip in tips)
