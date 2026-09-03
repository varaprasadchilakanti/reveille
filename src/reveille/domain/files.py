# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Where change concentrates in a repository, by path.

Two questions, both about files and neither about people:

* which paths absorb the most change, and
* what kinds of file the work actually goes into.

The first is the churn half of hotspot analysis as popularised by Adam
Tornhill in *Your Code as a Crime Scene* (2013), and resting on the
relative-churn measure of Nagappan and Ball, *Use of Relative Code Churn
Measures to Predict System Defect Density* (ICSE 2005). The full method
crosses churn with a complexity measure; Reveille reads history and never
file content, so it reports the churn axis alone and says so. A file that
changes often is a file to look at, not a file that is wrong.
"""

from __future__ import annotations

from collections import defaultdict

from reveille.domain.models import FileStats

#: Paths whose churn says more about tooling than about the work. Lock
#: files in particular are machine-generated and dominate any churn
#: ranking of a repository that has one -- `poetry.lock` is the single
#: largest source of changed lines in this repository, by a factor of
#: three, and tells a reader nothing they can act on.
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

    Ordered by total churn -- added plus deleted, not net, since a file
    that gains and loses a thousand lines has been worked on heavily
    whatever its final size. Ties break on commit count, then on path, so
    the ordering is total and the output is reproducible.

    Args:
        files: Per-path activity for the analysis window.
        limit: Maximum paths to return.
        include_generated: Whether to include machine-generated files.
            Off by default: a lock file usually tops the ranking and
            tells a reader nothing they can act on.

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

    Answers what kind of work a period contained -- source, tests,
    documentation, configuration -- without naming a single file or
    person. Extensions beyond `limit` are pooled into one trailing
    "other" entry rather than dropped, so the total is preserved.

    A path with no extension is reported as "(none)"; a dotfile such as
    `.gitignore` counts as having no extension, matching how a reader
    would describe it rather than treating `gitignore` as a type.

    Args:
        files: Per-path activity for the analysis window.
        limit: Maximum named extensions before pooling.

    Returns:
        A list of `(label, lines_changed)` pairs, largest first, with any
        pooled remainder last.
    """
    totals: dict[str, int] = defaultdict(int)
    for stats in files:
        totals[_extension_of(stats.path)] += stats.lines_changed

    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) <= limit:
        return ranked

    kept = ranked[:limit]
    pooled = sum(value for _label, value in ranked[limit:])
    # A pooled remainder of zero is noise: it happens when the tail is
    # exactly one extension with no churn, and an "other: 0" row invites
    # the question of what it is.
    return [*kept, ("other", pooled)] if pooled else kept


def _extension_of(path: str) -> str:
    """Return a displayable extension for a path.

    Args:
        path: A repository-relative path.

    Returns:
        The extension including its dot, or "(none)".
    """
    name = path.rsplit("/", 1)[-1]
    # A leading dot makes a dotfile, not an extension: `.gitignore` is a
    # file called gitignore, not a gitignore-typed file.
    if name.startswith("."):
        return "(none)"
    _, dot, extension = name.rpartition(".")
    if not dot or not extension:
        return "(none)"
    return f".{extension.lower()}"
