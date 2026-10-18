# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A machine-readable description of what Reveille can and cannot do.

Derived facts (version, commands, options, exit codes) are read from the
running program, so they cannot drift; judgements (purpose, refusals, caveats)
are written here. The reader may hold only the installed program, so limits
get as much room as features.

The JSON key `guarantees` is a schema field and keeps its name. Its entries are
properties that are designed and tested, not a warranty.

"""

from __future__ import annotations

import enum
from typing import Any, get_args

from reveille import __version__
from reveille.config import OutputFormat
from reveille.domain.models import SCHEMA_VERSION

# Versions this document's shape, independently of the release and the report schema.
CAPABILITIES_VERSION = "1.0"

_SUMMARY = (
    "Reads the commit history of a local Git repository and produces one "
    "self-contained offline report of commit activity over time."
)

# What the tool does, phrased so each statement can be checked.
_CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "id": "activity-calendar",
        "description": (
            "Render a per-day commit calendar for the repository or for one "
            "contributor, over a chosen date range."
        ),
    },
    {
        "id": "contributor-statistics",
        "description": (
            "Aggregate per-contributor commit counts, lines added and deleted, "
            "active days, and first and last commit dates."
        ),
    },
    {
        "id": "identity-resolution",
        "description": (
            "Merge identities using the repository's .mailmap, supporting all "
            "four documented forms, and fold GitHub noreply addresses onto the "
            "account they belong to."
        ),
    },
    {
        "id": "activity-concentration",
        "description": (
            "Report how evenly commits are distributed across the people in "
            "the window: how many account for a majority, and the full "
            "distribution as a Lorenz curve with its Gini coefficient. This "
            "characterises the repository as a whole, which is why it is in the "
            "default report while the per-person ranking is not."
        ),
    },
    {
        "id": "repository-summary",
        "description": (
            "Summarise a repository with `reveille summary`, in under 1 KB of "
            "text or about 2 KB of JSON: window, commit and people counts, Gini, "
            "quiet run and the written findings. It names nobody, but with one or "
            "two people, counts can identify someone."
        ),
    },
    {
        "id": "brief",
        "description": (
            "Say what changed since a tag, a commit or a date with `reveille brief "
            "--from <revision>` or `--since <date>` (with neither, since the latest "
            "tag): commits, people and automated "
            "accounts as counts, the most changed areas and file types, files "
            "added, areas active again after 90 quiet days and tags in the range. "
            "It names nobody, but with one or two people, counts can identify "
            "someone. A revision is read by ancestry, without line counts, "
            "and the analysed commit is printed so the next brief can start there."
        ),
    },
    {
        "id": "state",
        "description": (
            "Say where a repository stands now with `reveille state`: the branch or "
            "detached commit, upstream ahead/behind as of the last fetch, a merge, "
            "rebase, cherry-pick, revert or bisect in progress, conflicted paths, "
            "staged, modified, deleted, renamed and untracked counts with bounded "
            "lists, stashes, worktrees, local branches as counts, and the latest tag "
            "with the commits since it. Every Git call runs with optional locks and "
            "fsmonitor off and repository-defined content filters not run, so it "
            "neither rewrites the index nor starts a program the repository names. "
            "It names no author, but lists local paths (changed files and worktree "
            "directories, which can contain your login name) and the current "
            "branch name."
        ),
    },
    {
        "id": "who-changed",
        "description": (
            "Say who changed one file or directory with `reveille who-changed "
            "<path>`: its authors alphabetically, the five most recent, automated "
            "accounts and co-authors apart, with no count or date per person."
        ),
    },
    {
        "id": "repos",
        "description": (
            "Say which repositories in a directory are active, quiet or dormant with "
            "`reveille repos <directory>`: one row per repository, with its last "
            "commit, and the commits, people and automated accounts in a recent window "
            "as counts. It names nobody and counts nobody across repositories; a "
            "repository that cannot be read is a row saying why."
        ),
    },
    {
        "id": "co-authors",
        "description": (
            "Report identities credited by Co-authored-by trailers beside, not "
            "inside, authorship: a co-authored count per contributor and the "
            "identities credited only as co-authors. Trailers are not verified."
        ),
    },
    {
        "id": "area-authors",
        "description": (
            "When asked with --area-authors, list who changed each of the "
            "most-changed directories and when each was last changed, names "
            "alphabetically, with no count or date per person."
        ),
    },
    {
        "id": "structured-export",
        "description": (
            "Emit the same analysis as JSON or CSV for downstream processing, "
            "with a declared schema version."
        ),
    },
    {
        "id": "reproducible-output",
        "description": (
            "With --deterministic, produce byte-identical output for an "
            "unchanged repository on the same Reveille version, installed "
            "dependencies and Git settings, so a report "
            "can be regenerated and compared."
        ),
    },
)

# What the tool will not do.
_NOT_CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "id": "productivity-measurement",
        "description": (
            "Measure developer productivity, performance, contribution value, "
            "or code quality. The statistics count volume and regularity of "
            "commits and nothing else."
        ),
        "instead": (
            "For engineering effectiveness, use team-level delivery metrics. "
            "The SPACE framework (Forsgren et al., 2021) holds that developer "
            "productivity is about more than an individual's activity levels. "
            "DORA's metrics are defined for applications and services, not "
            "people."
        ),
    },
    {
        "id": "individual-assessment",
        "description": (
            "Support performance review, compensation, promotion, redundancy "
            "selection, or hiring decisions about a named person."
        ),
        "instead": (
            "Nothing here is fit for that purpose. The contributor ranking is a "
            "visual ordering of commit volume, not an evaluation. The scored "
            "table is off by default and is enabled only by an explicit --ranking "
            "flag or an `enabled = true` entry in a reveille.toml. JSON and CSV "
            "output carry a `rank` column in table order: by commits, or by score "
            "with --ranking."
        ),
    },
    {
        "id": "bus-factor",
        "description": (
            "Compute a bus factor. Commit concentration measures who has been "
            "active, not who understands which code."
        ),
        "instead": (
            "A real bus factor needs per-file ownership analysis, which this tool does not perform."
        ),
    },
    {
        "id": "code-analysis",
        "description": (
            "Read, parse, lint, or evaluate source code, diff content, file "
            "contents, or any part of a commit message other than its "
            "Co-authored-by trailers. What is read is commit metadata -- object "
            "name, author name, author email, timestamp -- those trailers, and, "
            "per file in each commit, the path and the number of lines added "
            "and deleted, as reported by `git log --numstat`. How many lines "
            "changed in a file, never which lines. Reveille receives paths, "
            "counts and, for `state`, status letters; Git reads the files to "
            "compute them."
        ),
        "instead": "Use a static analysis tool or a code search tool.",
    },
    {
        "id": "remote-access",
        "description": (
            "Clone, fetch, or contact any network service, including the forge "
            "the repository came from. It reads a path on disk."
        ),
        "instead": "Clone the repository first, then point Reveille at it.",
    },
    {
        "id": "repository-modification",
        "description": (
            "Alter a repository's Git data: history, refs, index, objects or "
            "configuration. "
            "`generate` writes only the report you name; `init` writes only "
            "the configuration files you ask it for."
        ),
        "instead": "",
    },
    {
        "id": "cross-repository-aggregation",
        "description": (
            "Combine several repositories into one per-person view. Not offered "
            "by design. Separate JSON outputs can still be joined by email "
            "address, so this limits convenience, not capability."
        ),
        "instead": "Run Reveille per repository and compare the reports.",
    },
)

# Caveats that change how a number is read; documented behaviour.
_CAVEATS: tuple[dict[str, str], ...] = (
    {
        "id": "merge-commits-excluded",
        "description": (
            "Merge commits are excluded unconditionally, so commit counts are "
            "lower than `git log` reports for the same range, by the number "
            "`merge_commits_excluded` gives in the JSON."
        ),
    },
    {
        "id": "automated-accounts-are-not-people",
        "description": (
            "Contributor counts, commit concentration and the Gini count people. "
            "An account whose name or address carries [bot] is counted in the "
            "commit and line totals and stated separately, not in those figures; "
            "an automated account without that suffix is counted as a person."
        ),
    },
    {
        "id": "identity-is-self-asserted",
        "description": (
            "Author name and email come from commit metadata, which the author "
            "sets locally. They are not verified and can be set to anything."
        ),
    },
    {
        "id": "lines-changed-is-noisy",
        "description": (
            "Lines added and deleted count every line in a diff, so a lockfile "
            "update, a vendored dependency, or a reformatting pass can dwarf "
            "months of considered work."
        ),
    },
    {
        "id": "window-affects-recency",
        "description": (
            "Recency is measured against the analysis window, so it is a "
            "property of the range you chose as much as of the contributor."
        ),
    },
    {
        "id": "history-may-be-partial",
        "description": (
            "A shallow clone is analysed as the history it holds, and commits "
            "dated after the end of a default window are counted in no figure. "
            "Both are stated in the report and in provenance (shallow_clone, "
            "commits_dated_after_window); read them before reading the totals."
        ),
    },
    {
        "id": "output-contains-personal-data",
        "description": (
            "The report includes contributor names and email addresses. It is a "
            "document containing personal data; whoever circulates it is "
            "responsible for that. --ranking scores named people and "
            "--area-authors names who changed each area; both are off unless asked for."
        ),
    },
)

# Properties designed into every invocation, each asserted by a test. Not a warranty.
_GUARANTEES: tuple[dict[str, str], ...] = (
    {
        "id": "offline",
        "description": (
            "The tool makes no outbound call, and the generated report loads no "
            "remote resource. A SHA-256 repository is refused. A partial clone is "
            "refused rather than read, because reading it would make Git fetch. Programs a "
            "repository's own .git/config can make its reads start are switched "
            "off (signature checking, fsmonitor, content filters during `state`); "
            "Git has many settings, and one not switched off is outside these "
            "properties."
        ),
    },
    {
        "id": "read-only-analysis",
        "description": (
            "Analysis never changes the repository's Git data: its history, "
            "refs, index, objects or configuration. An output path inside "
            ".git is refused. The report is written where you say, by default "
            "reveille-report.html in the repository root. A repository whose "
            "configuration sets its working tree to another directory "
            "(core.worktree) is refused. `reveille init` "
            "writes only the files you ask it for: reveille.toml, and "
            ".mailmap with --mailmap."
        ),
    },
    {
        "id": "no-telemetry",
        "description": "Nothing is reported, phoned home, or stored elsewhere.",
    },
    {
        "id": "self-contained-output",
        "description": (
            "The HTML report is a single file that renders with no external dependency."
        ),
    },
)


def _commands(app: Any) -> list[dict[str, Any]]:
    """Describe the CLI surface by inspecting the live Typer application.

    Derived, not written down, so it cannot disagree with the program.

    Args:
        app: The Typer application object.

    Returns:
        One entry per command, each with its options.
    """
    import typer.main

    group = typer.main.get_command(app)

    # An empty command list (for example if Click restructured) is never true,
    # so fail rather than describe a tool with no commands.
    commands = getattr(group, "commands", None)
    if not commands:
        raise RuntimeError(
            "Could not read the command list from the CLI application. This "
            "usually means the installed Click or Typer version changed its "
            "internals. Refusing to emit a capability document that would "
            "describe this tool as having no commands."
        )

    described: list[dict[str, Any]] = []

    for name, command in sorted(commands.items()):
        options: list[dict[str, Any]] = []
        for param in command.params:
            opts = getattr(param, "opts", [])
            if not opts:
                continue
            options.append(
                {
                    "flags": list(opts),
                    "help": (getattr(param, "help", None) or "").strip(),
                    "required": bool(getattr(param, "required", False)),
                    "is_flag": bool(getattr(param, "is_flag", False)),
                }
            )
        described.append(
            {
                "name": name,
                "summary": (command.help or "").strip().split("\n")[0],
                "options": options,
            }
        )
    return described


# Hand-written because `member.__doc__` on `ExitCode` returns the class
# docstring. Names and numbers come from the enum; a test checks this mapping
# covers every member.
_EXIT_CODE_MEANINGS: dict[str, str] = {
    "SUCCESS": "The command ran and its answer is affirmative.",
    "NEGATIVE": (
        "The command ran correctly and its answer is negative: the "
        "repository state does not satisfy the request, such as an analysis "
        "window containing no commits."
    ),
    "CANNOT_RUN": (
        "The command could not run at all: invalid invocation, invalid "
        "configuration, a path that is not a readable Git repository, or an "
        "output location that cannot be written."
    ),
}


def _exit_codes(exit_code_enum: type[enum.IntEnum]) -> list[dict[str, Any]]:
    """Describe the exit-code contract from the enum that defines it.

    Args:
        exit_code_enum: The ExitCode enumeration.

    Returns:
        One entry per code, in ascending numeric order.
    """
    return [
        {
            "code": int(member.value),
            "name": member.name.lower().replace("_", "-"),
            "meaning": _EXIT_CODE_MEANINGS.get(member.name, ""),
        }
        for member in sorted(exit_code_enum, key=lambda m: int(m.value))
    ]


def build_capabilities(app: Any, exit_code_enum: type[enum.IntEnum]) -> dict[str, Any]:
    """Assemble the full capability document.

    Args:
        app: The Typer application, used to derive the command surface.
        exit_code_enum: The ExitCode enumeration, used to derive exit codes.

    Returns:
        A JSON-serialisable mapping describing the tool.
    """
    return {
        "capabilities_version": CAPABILITIES_VERSION,
        "name": "reveille",
        "version": __version__,
        "summary": _SUMMARY,
        "output_schema_version": SCHEMA_VERSION,
        "output_formats": _output_formats(),
        "guarantees": [dict(item) for item in _GUARANTEES],
        "can": [dict(item) for item in _CAPABILITIES],
        "cannot": [dict(item) for item in _NOT_CAPABILITIES],
        "caveats": [dict(item) for item in _CAVEATS],
        "commands": _commands(app),
        "exit_codes": _exit_codes(exit_code_enum),
    }


def _output_formats() -> list[str]:
    """The output formats the tool accepts, derived from `config.OutputFormat`."""
    formats = get_args(OutputFormat)
    if not formats:
        raise RuntimeError(
            "Could not read the output formats from config.OutputFormat. "
            "Refusing to emit a capability document with a format list it "
            "cannot derive."
        )
    return [str(item) for item in formats]


#: The `can` entry that describes each command, where its id differs from the name.
_DESCRIBED_BY = {"summary": "repository-summary"}


def command_capabilities(document: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Narrow the capability document to one command, its description and the exit codes.

    Args:
        document: The mapping returned by `build_capabilities`.
        name: A command name, such as "state".

    Returns:
        The narrowed document, or None if there is no such command.
    """
    commands = {command["name"]: command for command in document["commands"]}
    if name not in commands:
        return None
    described = {item["id"]: item["description"] for item in document["can"]}
    command = dict(commands[name])
    command["description"] = described.get(_DESCRIBED_BY.get(name, name), command["summary"])
    return {
        "capabilities_version": document["capabilities_version"],
        "name": document["name"],
        "version": document["version"],
        "command": command,
        "exit_codes": document["exit_codes"],
    }


def render_command_text(document: dict[str, Any]) -> str:
    """Render one command's capabilities for a terminal.

    Args:
        document: The mapping returned by `command_capabilities`.

    Returns:
        A plain-text rendering.
    """
    command = document["command"]
    lines = [f"reveille {command['name']} ({document['version']})", "", command["description"]]
    lines += ["", "OPTIONS"]
    lines += [f"  {', '.join(o['flags'])}  {o['help']}" for o in command["options"]]
    lines += ["", "EXIT CODES"]
    lines += [f"  {item['code']}  {item['meaning']}" for item in document["exit_codes"]]
    return "\n".join(lines)


def render_text(document: dict[str, Any]) -> str:
    """Render the capability document for a person reading a terminal.

    Args:
        document: The mapping returned by `build_capabilities`.

    Returns:
        A plain-text rendering.
    """
    lines: list[str] = [
        f"reveille {document['version']}",
        "",
        document["summary"],
        "",
        "PROPERTIES (designed and tested; not a warranty)",
    ]
    lines += [f"  - {item['description']}" for item in document["guarantees"]]

    lines += ["", "WHAT IT DOES"]
    lines += [f"  - {item['description']}" for item in document["can"]]

    lines += ["", "WHAT IT DOES NOT DO"]
    for item in document["cannot"]:
        lines.append(f"  - {item['description']}")
        if item.get("instead"):
            lines.append(f"      {item['instead']}")

    lines += ["", "READ THE NUMBERS WITH THESE IN MIND"]
    lines += [f"  - {item['description']}" for item in document["caveats"]]

    lines += ["", "EXIT CODES"]
    lines += [f"  {item['code']}  {item['meaning']}" for item in document["exit_codes"]]

    lines += [
        "",
        f"Structured output schema version: {document['output_schema_version']}",
        "Machine-readable form: reveille capabilities --format json",
        "",
    ]
    return "\n".join(lines)
