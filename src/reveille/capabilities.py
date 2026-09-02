# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A machine-readable description of what Reveille can and cannot do.

Most tools describe themselves in prose that drifts from the code within two
releases. This module keeps the two apart deliberately:

* **Derived facts** — the version, the output schema version, the commands and
  their options, the exit codes — are read from the running program. They
  cannot drift, because there is nothing to keep in sync.
* **Stated judgements** — what the tool is *for*, what it refuses to claim, and
  the caveats a reader needs before trusting a number — are written here in one
  place, because no amount of introspection can derive them.

The audience is a program, not a person. A coding agent deciding whether to
reach for Reveille should be able to ask it directly rather than guess from a
README, and the answer should include the *limits* as prominently as the
features. A tool that only advertises what it is good at is one an agent will
misuse.

`docs/` remains the human-facing reference; `llms.txt` remains the pointer for
an assistant reading the repository. This is the answer for a program holding
the installed binary and nothing else.
"""

from __future__ import annotations

import enum
from typing import Any

from reveille import __version__
from reveille.domain.models import SCHEMA_VERSION

# The contract version of this document itself, so a consumer can tell a shape
# change from a content change. Independent of both the release version and the
# report's schema version, because all three move for different reasons.
CAPABILITIES_VERSION = "1.0"

_SUMMARY = (
    "Reads the commit history of a local Git repository and produces one "
    "self-contained offline report of contributor activity over time."
)

# What the tool does, phrased as claims that could be checked.
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
            "Report how many contributors account for a majority of commits in the window."
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
            "Produce byte-identical output for an unchanged repository, so a "
            "report can be regenerated and compared."
        ),
    },
)

# What the tool will not do. This list is the load-bearing half of the
# document: it is what stops a caller reaching for Reveille to answer a
# question it cannot answer.
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
            "Both DORA and SPACE state explicitly that their measures must not "
            "be applied to individuals."
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
            "visual ordering of commit volume, not an evaluation. It is off by "
            "default and must be requested explicitly with --ranking."
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
            "Read, parse, lint, or evaluate source code, commit messages, "
            "diffs, or file contents. Only commit metadata is read: object "
            "name, author name, author email, and timestamp."
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
            "Write to, stage in, or otherwise alter the repository it reads. "
            "The only file it writes is the report you name."
        ),
        "instead": "",
    },
    {
        "id": "cross-repository-aggregation",
        "description": (
            "Combine several repositories into one per-person view. This was "
            "considered and deliberately cut: aggregating an individual's "
            "activity across repositories builds a surveillance tool."
        ),
        "instead": "Run Reveille per repository and compare the reports.",
    },
)

# Caveats that change how a number should be read. Every one of these is a
# documented behaviour, not a known bug.
_CAVEATS: tuple[dict[str, str], ...] = (
    {
        "id": "merge-commits-excluded",
        "description": (
            "Merge commits are excluded unconditionally, so commit counts are "
            "lower than `git log` reports for the same range."
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
        "id": "output-contains-personal-data",
        "description": (
            "The report includes contributor names and email addresses. It is a "
            "document containing personal data; whoever circulates it is "
            "responsible for that."
        ),
    },
)

# Properties that hold for every invocation. These are the ones worth checking
# against, because each is asserted by a test.
_GUARANTEES: tuple[dict[str, str], ...] = (
    {
        "id": "offline",
        "description": (
            "No network call is made at any point, and the generated report "
            "loads no remote resource."
        ),
    },
    {
        "id": "read-only",
        "description": "The analysed repository is never modified.",
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

    Derived rather than written down, so it cannot disagree with the program.
    A README once documented a subcommand that had never existed; anything a
    machine reads about this tool should come from the tool.

    Args:
        app: The Typer application object.

    Returns:
        One entry per command, each with its options.
    """
    import typer.main

    group = typer.main.get_command(app)
    described: list[dict[str, Any]] = []

    for name, command in sorted(getattr(group, "commands", {}).items()):
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


# Meanings for the exit codes. Kept as an explicit mapping rather than read
# from the enum: the per-member strings in `ExitCode` are bare expressions, not
# docstrings, so `member.__doc__` returns the *class* docstring and every code
# would carry the same wrong text. The names and numbers below are still
# derived from the enum, and `tests/unit/test_capabilities.py` asserts this
# mapping covers every member, so a new code cannot be added without one.
_EXIT_CODE_MEANINGS: dict[str, str] = {
    "SUCCESS": "The command ran and its answer is affirmative.",
    "NEGATIVE": (
        "The command ran correctly and its answer is negative -- the "
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
        "output_formats": ["html", "json", "csv"],
        "guarantees": [dict(item) for item in _GUARANTEES],
        "can": [dict(item) for item in _CAPABILITIES],
        "cannot": [dict(item) for item in _NOT_CAPABILITIES],
        "caveats": [dict(item) for item in _CAVEATS],
        "commands": _commands(app),
        "exit_codes": _exit_codes(exit_code_enum),
    }


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
        "GUARANTEES",
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
