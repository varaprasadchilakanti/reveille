# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Where change concentrates by path, and what kinds of file it goes into.

Churn half of hotspot analysis (Tornhill, 2013; Nagappan and Ball, ICSE 2005),
without the complexity axis: file content is never read. Frequent change marks
a file to look at, not a file that is wrong.
"""

from __future__ import annotations

from collections import defaultdict

from reveille.domain.models import FileStats

#: Machine-generated lock files: dominant churn, nothing actionable.
_GENERATED_NAMES = frozenset(
    {
        "poetry.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
        "pipfile.lock",
    }
)


#: The type-breakdown entry every generated file is reported under.
GENERATED_LABEL = "lock files"


def is_generated(path: str) -> bool:
    """Return whether a path is a machine-generated file.

    Args:
        path: A repository-relative path.

    Returns:
        True if the file is one a tool writes rather than a person.
    """
    return path.rsplit("/", 1)[-1].lower() in _GENERATED_NAMES


def hotspots(
    files: list[FileStats],
    limit: int = 10,
    *,
    include_generated: bool = False,
) -> list[FileStats]:
    """Return the paths absorbing the most change, most first.

    Ordered by churn (added plus deleted, not net), then commit count, then
    path, so the order is total and reproducible.

    Args:
        files: Per-path activity for the analysis window.
        limit: Maximum paths to return.
        include_generated: Whether to include machine-generated files.

    Returns:
        At most `limit` entries, highest churn first.
    """
    candidates = [f for f in files if include_generated or not is_generated(f.path)]
    candidates.sort(key=lambda f: (-f.lines_changed, -f.commits, f.path))
    return candidates[:limit]


def extension_breakdown(
    files: list[FileStats],
    limit: int = 8,
) -> list[tuple[str, int]]:
    """Return churn totalled by file extension, largest first.

    Beyond `limit`, extensions pool into a trailing "other". Dotfiles count as
    "(none)"; lock files form one "lock files" entry.

    Args:
        files: Per-path activity for the analysis window.
        limit: Maximum named extensions before pooling.

    Returns:
        A list of `(label, lines_changed)` pairs, largest first, with any
        pooled remainder last.
    """
    totals: dict[str, int] = defaultdict(int)
    for stats in files:
        label = GENERATED_LABEL if is_generated(stats.path) else _extension_of(stats.path)
        totals[label] += stats.lines_changed

    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) <= limit:
        return ranked

    kept = ranked[:limit]
    pooled = sum(value for _label, value in ranked[limit:])
    # An "other: 0" row is noise.
    return [*kept, ("other", pooled)] if pooled else kept


def file_type(path: str) -> str:
    """Return the label a path is counted under: its extension, or "lock files".

    Args:
        path: A repository-relative path.

    Returns:
        The extension (".py"), "(none)", or the lock-file label.
    """
    return GENERATED_LABEL if is_generated(path) else _extension_of(path)


def generated_churn(files: list[FileStats]) -> tuple[int, int]:
    """Return how many generated files changed, and their lines changed.

    What the hotspot ranking leaves out, so the report can say so.

    Args:
        files: Per-path activity for the analysis window.

    Returns:
        A `(files, lines_changed)` pair; `(0, 0)` when there are none.
    """
    generated = [f for f in files if is_generated(f.path)]
    return len(generated), sum(f.lines_changed for f in generated)


def _extension_of(path: str) -> str:
    """Return a displayable extension for a path.

    Args:
        path: A repository-relative path.

    Returns:
        The extension including its dot, or "(none)".
    """
    name = path.rsplit("/", 1)[-1]
    # A leading dot makes a dotfile, not an extension.
    if name.startswith("."):
        return "(none)"
    _, dot, extension = name.rpartition(".")
    if not dot or not extension:
        return "(none)"
    return f".{extension.lower()}"
