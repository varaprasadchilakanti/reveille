# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Configuration model for Reveille report generation.

ReportConfig is the one validated input from CLI to service, built from flags
and an optional TOML file; flags always take precedence.
"""

from __future__ import annotations

import datetime
import errno
import json
import os
import stat
import tomllib
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from reveille.exceptions import ConfigurationError

OutputFormat = Literal["html", "json", "csv"]


class RankingWeights(BaseModel):
    """Weights for the ranking composite score; they must sum to 1.0.

    **The defaults are a documented judgement, not a derived model**; the
    reasoning is in docs/USER_GUIDE.md. The composite measures volume and
    regularity of commits, not contribution.

    """

    commits: float = Field(default=0.30, ge=0.0, le=1.0)
    lines: float = Field(default=0.25, ge=0.0, le=1.0)
    consistency: float = Field(default=0.25, ge=0.0, le=1.0)
    recency: float = Field(default=0.20, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> RankingWeights:
        """Validate that all four weights sum to 1.0 within floating point tolerance.

        Returns:
            The validated RankingWeights instance.

        Raises:
            ValueError: If the sum deviates from 1.0 by more than 1e-6.
        """
        total = self.commits + self.lines + self.consistency + self.recency
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Ranking weights must sum to 1.0, got {total:.6f}. "
                "Adjust weights so that commits + lines + consistency + recency = 1.0."
            )
        return self


class ReportConfig(BaseModel):
    """Validated configuration for a single report generation run.

    Raises:
        ValueError: If since > until.
    """

    repo_path: Path = Field(default=Path("."))
    output_path: Path = Field(default=Path("reveille-report.html"))
    title: str | None = Field(default=None)
    branch: str | None = Field(default=None)
    since: datetime.date | None = Field(default=None)
    until: datetime.date | None = Field(default=None)
    exclude_authors: list[str] = Field(default_factory=list)
    # Repository-relative paths left out of every figure, matched literally.
    exclude_paths: list[str] = Field(default_factory=list)
    min_commits: int = Field(default=1, ge=1)
    # Off by default: it scores named individuals, inviting the use the docs
    # forbid. Opt in with --ranking or `[ranking] enabled = true` (ADR 0010).
    ranking_enabled: bool = Field(default=False)
    ranking_weights: RankingWeights = Field(default_factory=RankingWeights)
    # Off by default and not implied by the ranking: it names people (ADR 0013).
    area_authors_enabled: bool = Field(default=False)
    area_depth: int = Field(default=3, ge=1, le=10)
    output_format: OutputFormat = Field(default="html")
    deterministic: bool = Field(default=False)
    # Bounds every list of people in JSON and CSV (ADR 0015); None keeps all.
    limit: int | None = Field(default=None, ge=1)
    # Every address replaced by a per-report token, for a report that is shared.
    hide_emails: bool = Field(default=False)

    @field_validator("exclude_paths")
    @classmethod
    def exclude_paths_must_be_repository_relative(cls, paths: list[str]) -> list[str]:
        """Normalise each excluded path and refuse one Git could not match as meant.

        Args:
            paths: The paths as given.

        Returns:
            The paths with surrounding spaces and trailing slashes removed.

        Raises:
            ValueError: If a path is empty, absolute, climbs out with `..`, or
                carries a NUL character.
        """
        normalised: list[str] = []
        for raw in paths:
            path = raw.strip().rstrip("/")
            while path.startswith("./"):
                path = path[2:]
            if not path or path == ".":
                raise ValueError(f"an excluded path is empty: {raw!r}.")
            if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
                raise ValueError(
                    f"an excluded path must be relative to the repository root, not {raw!r}."
                )
            if ".." in path.split("/"):
                raise ValueError(f"an excluded path must not contain '..': {raw!r}.")
            # A tab or a newline is a byte a path may hold, and every output escapes
            # it; NUL is the one no path, and no argument to Git, can carry.
            if "\0" in path:
                raise ValueError(f"an excluded path carries a NUL character: {raw!r}.")
            normalised.append(path)
        return normalised

    @model_validator(mode="after")
    def since_must_precede_until(self) -> ReportConfig:
        """Validate that the since date does not exceed the until date.

        Returns:
            The validated ReportConfig instance.

        Raises:
            ValueError: If since is later than until.
        """
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError(f"since ({self.since}) must be earlier than until ({self.until}).")
        return self


class ReportConfigKwargs(TypedDict, total=False):
    """Typed keyword arguments for ReportConfig, assembled from TOML then flags.

    total=False: an absent key takes the field default. since and until are
    plain dates because, when present, they are never None.
    """

    repo_path: Path
    output_path: Path
    title: str | None
    branch: str | None
    since: datetime.date
    until: datetime.date
    exclude_authors: list[str]
    exclude_paths: list[str]
    min_commits: int
    ranking_enabled: bool
    ranking_weights: RankingWeights
    area_authors_enabled: bool
    area_depth: int
    output_format: OutputFormat
    deterministic: bool
    limit: int
    hide_emails: bool


#: Larger than any configuration a person writes; the file can come with a clone.
_MAX_CONFIG_BYTES = 1_048_576


def output_path(text: str) -> Path:
    """Return the output path `text` names; only `-` itself means standard output.

    `Path` reads `./-` as `-`, so it would have gone to stdout, not to a file
    named `-`. Such a spelling is made absolute, as the current directory gives it.

    Args:
        text: The path as given.

    Returns:
        The path; `Path("-")` only for `-`.
    """
    path = Path(text)
    return Path(os.path.abspath(text)) if text != "-" and path == Path("-") else path


def _read_config_bytes(path: Path, *, follow_links: bool) -> bytes:
    """Read a configuration file that is a regular file of a plausible size.

    Opened without waiting, then checked on the open file, so a named pipe or a
    device (`/dev/zero` behind a link) is refused, not waited on or read without end.
    Without `follow_links`, a link in its place when it is opened is refused too.
    """
    if follow_links:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    else:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ConfigurationError(
                f"Configuration file '{path}' is not a regular file (a directory, a "
                "named pipe or a device), so it is not read."
            )
        data = handle.read(_MAX_CONFIG_BYTES + 1)
    if len(data) > _MAX_CONFIG_BYTES:
        raise ConfigurationError(
            f"Configuration file '{path}' is larger than {_MAX_CONFIG_BYTES:,} bytes, more "
            "than any configuration a person writes, so it is not read."
        )
    return data


#: Every key Reveille reads, by table. Anything else in the file has no effect.
_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "report": frozenset(
        {"title", "output", "branch", "since", "until", "format"}
        | {"deterministic", "hide_emails", "limit"}
    ),
    "filters": frozenset({"min_commits", "exclude_authors", "exclude_paths"}),
    "ranking": frozenset({"enabled", "weights"}),
    "ranking.weights": frozenset({"commits", "lines", "consistency", "recency"}),
    "areas": frozenset({"enabled", "depth"}),
}

#: Unknown keys named in full before the rest are counted, so the note stays one line.
_UNKNOWN_KEYS_NAMED = 10


def _toml_key(key: str) -> str:
    """Return a key as TOML would write it: bare when it can be, quoted otherwise."""
    if key and all(c.isascii() and (c.isalnum() or c in "_-") for c in key):
        return key
    return json.dumps(key)


def _unknown_keys(raw: dict[str, Any]) -> list[str]:
    """Return each table and key in the file that Reveille does not read.

    Args:
        raw: The parsed document, its four tables already checked to be tables.

    Returns:
        Each unknown table as `[name]` and key as `[table] key`, in file order.
    """
    unknown: list[str] = []
    for section, table in raw.items():
        if section not in _KNOWN_KEYS:
            unknown.append(f"[{_toml_key(section)}]")
            continue
        for key, value in table.items():
            if key not in _KNOWN_KEYS[section]:
                unknown.append(f"[{section}] {_toml_key(key)}")
            elif section == "ranking" and key == "weights" and isinstance(value, dict):
                unknown.extend(
                    f"[ranking.weights] {_toml_key(name)}"
                    for name in value
                    if name not in _KNOWN_KEYS["ranking.weights"]
                )
    return unknown


def describe_unknown_keys(unknown: list[str]) -> str:
    """Return one sentence naming the keys a configuration sets that have no effect.

    Args:
        unknown: The keys, as `read_config_file` returns them; not empty.

    Returns:
        The sentence, naming at most ten keys and counting the rest.
    """
    named = ", ".join(unknown[:_UNKNOWN_KEYS_NAMED])
    rest = len(unknown) - _UNKNOWN_KEYS_NAMED
    if rest > 0:
        named += f" and {rest:,} more"
    return f"Reveille does not read {named}, so {'it has' if len(unknown) == 1 else 'they have'} no effect. Check the spelling."


def load_config_from_toml(path: Path) -> ReportConfigKwargs:
    """Load and flatten configuration values from a Reveille TOML file.

    Only keys present in the file are returned, so absent keys override nothing.

    Args:
        path: Path to the TOML configuration file.

    Returns:
        ReportConfig keyword arguments.

    Raises:
        ConfigurationError: If the file is missing, unreadable, not TOML, or invalid.
    """
    return read_config_file(path)[0]


def read_config_file(
    path: Path, *, follow_links: bool = True
) -> tuple[ReportConfigKwargs, list[str]]:
    """Load a Reveille TOML file, and say which of its keys Reveille does not read.

    Args:
        path: Path to the TOML configuration file.
        follow_links: False to refuse a symbolic link at `path` itself.

    Returns:
        ReportConfig keyword arguments, and each unknown table and key. An unknown
        key is not an error, so a file written for another version still runs.

    Raises:
        ConfigurationError: If the file is missing, unreadable, not TOML, or invalid.
    """
    try:
        # "utf-8-sig": an editor that writes a byte-order mark still wrote UTF-8.
        raw = tomllib.loads(_read_config_bytes(path, follow_links=follow_links).decode("utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: '{path}'.") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Configuration file is not valid TOML: {exc}") from exc
    except RecursionError as exc:
        raise ConfigurationError(
            f"Configuration file '{path}' is nested too deeply to be a configuration."
        ) from exc
    # Caught so they exit as configuration errors, not tracebacks with exit 1
    # ("negative answer"). TOML must be UTF-8; a directory is not a file.
    except UnicodeDecodeError as exc:
        raise ConfigurationError(
            f"Configuration file '{path}' is not UTF-8 text, which TOML requires."
        ) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP and not follow_links:
            raise ConfigurationError(
                f"Configuration file '{path}' is a symbolic link, which is not followed."
            ) from exc
        raise ConfigurationError(f"Configuration file '{path}' cannot be read: {exc}") from exc

    for section in ("report", "filters", "ranking", "areas"):
        if not isinstance(raw.get(section, {}), dict):
            raise ConfigurationError(
                f"[{section}] in '{path}' must be a table of settings, not {raw[section]!r}."
            )
    parts: dict[str, Any] = {}
    parts.update(_parse_report_section(raw.get("report", {})))
    parts.update(_parse_filters_section(raw.get("filters", {})))
    parts.update(_parse_ranking_section(raw.get("ranking", {})))
    parts.update(_parse_areas_section(raw.get("areas", {})))
    return cast(ReportConfigKwargs, parts), _unknown_keys(raw)


def _parse_report_section(report: dict[str, Any]) -> dict[str, Any]:
    """Parse the [report] section of a Reveille TOML configuration file.

    Args:
        report: The raw [report] table from the parsed TOML document.

    Returns:
        A partial kwargs dict for ReportConfig construction.

    Raises:
        ConfigurationError: If a date field contains an invalid ISO 8601 string.
    """
    kwargs: dict[str, Any] = {}
    # Type-checked: `str()` on a table or array would succeed with nonsense.
    for key, field in (("title", "title"), ("output", "output_path"), ("branch", "branch")):
        if key not in report:
            continue
        value = report[key]
        if not isinstance(value, str):
            raise ConfigurationError(
                f"Invalid '{key}' in the [report] section of the configuration "
                f"file: expected a string, got {type(value).__name__}."
            )
        if field == "output_path" and value.endswith(("/", os.sep)):
            # `Path` drops the separator, and the report would take the directory's name.
            raise ConfigurationError(
                f"[report] output {value!r} names a directory, not a file. Give a file name in it."
            )
        kwargs[field] = output_path(value) if field == "output_path" else value
    for field in ("since", "until"):
        if field in report:
            try:
                kwargs[field] = datetime.date.fromisoformat(str(report[field]))
            except ValueError as exc:
                raise ConfigurationError(
                    f"Invalid '{field}' date in configuration file: "
                    f"'{report[field]}'. Expected YYYY-MM-DD."
                ) from exc
            if field == "until" and kwargs[field] == datetime.date.max:
                # An inclusive end is read up to the next day, which does not exist.
                raise ConfigurationError(f"'until' must be before {datetime.date.max}.")
    if "format" in report:
        kwargs["output_format"] = cast(OutputFormat, str(report["format"]))
    kwargs.update(_parse_report_switches(report))
    return kwargs


def _parse_report_switches(report: dict[str, Any]) -> dict[str, Any]:
    """Parse the [report] keys that are a boolean or a whole number, strictly.

    Args:
        report: The raw [report] table.

    Returns:
        The keys present, typed.

    Raises:
        ConfigurationError: If a value has the wrong type.
    """
    kwargs: dict[str, Any] = {}
    # Strict, like [ranking] enabled: bool("false") is True.
    for key in ("deterministic", "hide_emails"):
        if key in report:
            kwargs[key] = _strict_bool("report", key, report[key])
    if "limit" in report:
        kwargs["limit"] = _strict_int("report", "limit", report["limit"])
    return kwargs


def _strict_bool(section: str, key: str, value: object) -> bool:
    """Return a TOML boolean, refusing anything else.

    Args:
        section: The table the key is in, for the message.
        key: The key, for the message.
        value: The parsed value.

    Returns:
        The value.

    Raises:
        ConfigurationError: If not a boolean (a quoted "false" is truthy).
    """
    if not isinstance(value, bool):
        raise ConfigurationError(f"[{section}] {key} must be true or false, not {value!r}.")
    return value


def _strict_int(section: str, key: str, value: object) -> int:
    """Return a TOML integer, refusing booleans, strings and floats.

    Args:
        section: The table the key is in, for the message.
        key: The key, for the message.
        value: The parsed value.

    Returns:
        The value.

    Raises:
        ConfigurationError: If the value is not a whole number.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"[{section}] {key} must be a whole number, not {value!r}.")
    return value


def _parse_filters_section(filters: dict[str, Any]) -> dict[str, Any]:
    """Parse the [filters] section of a Reveille TOML configuration file.

    Args:
        filters: The raw [filters] table from the parsed TOML document.

    Returns:
        A partial kwargs dict for ReportConfig construction.

    Raises:
        ConfigurationError: If a value has the wrong type.
    """
    kwargs: dict[str, Any] = {}
    if "min_commits" in filters:
        value = filters["min_commits"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigurationError(
                f"[filters] min_commits must be a whole number, not {value!r}."
            )
        kwargs["min_commits"] = value
    if "exclude_authors" in filters:
        authors = filters["exclude_authors"]
        # A bare string would be split into characters by `list()`.
        if not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
            raise ConfigurationError(
                f"[filters] exclude_authors must be a list of strings, not {authors!r}."
            )
        kwargs["exclude_authors"] = list(authors)
    if "exclude_paths" in filters:
        paths = filters["exclude_paths"]
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ConfigurationError(
                f"[filters] exclude_paths must be a list of strings, not {paths!r}."
            )
        kwargs["exclude_paths"] = list(paths)
    return kwargs


def _parse_areas_section(areas: dict[str, Any]) -> dict[str, Any]:
    """Parse the [areas] section of a Reveille TOML configuration file.

    Args:
        areas: The raw [areas] table from the parsed TOML document.

    Returns:
        A partial kwargs dict for ReportConfig construction.

    Raises:
        ConfigurationError: If `enabled` or `depth` has the wrong type.
    """
    kwargs: dict[str, Any] = {}
    if "enabled" in areas:
        # Strict: "false" is a truthy string, and an accidental enable names people.
        value = areas["enabled"]
        if not isinstance(value, bool):
            raise ConfigurationError(
                f"[areas] enabled must be true or false, not {value!r}. "
                'Quoted values such as "false" are strings, and every '
                "non-empty string would count as true."
            )
        kwargs["area_authors_enabled"] = value
    if "depth" in areas:
        depth = areas["depth"]
        if isinstance(depth, bool) or not isinstance(depth, int):
            raise ConfigurationError(f"[areas] depth must be a whole number, not {depth!r}.")
        kwargs["area_depth"] = depth
    return kwargs


def _parse_ranking_section(ranking: dict[str, Any]) -> dict[str, Any]:
    """Parse the [ranking] section of a Reveille TOML configuration file.

    Args:
        ranking: The raw [ranking] table from the parsed TOML document.

    Returns:
        A partial kwargs dict for ReportConfig construction.
    """
    kwargs: dict[str, Any] = {}
    if "enabled" in ranking:
        # Strict, not `bool(...)`: `enabled = "false"` must never produce tiers.
        value = ranking["enabled"]
        if not isinstance(value, bool):
            raise ConfigurationError(
                f"[ranking] enabled must be true or false, not {value!r}. "
                'Quoted values such as "false" are strings, and every '
                "non-empty string would count as true."
            )
        kwargs["ranking_enabled"] = value
    if "weights" in ranking:
        w = ranking["weights"]
        if not isinstance(w, dict):
            raise ConfigurationError(
                f"[ranking] weights must be a table of named weights, not {w!r}."
            )
        for name in ("commits", "lines", "consistency", "recency"):
            # A number, as TOML writes one: `float(True)` is 1.0, and a quoted
            # value is a string, refused as `enabled = "false"` is.
            if name in w and (isinstance(w[name], bool) or not isinstance(w[name], int | float)):
                raise ConfigurationError(
                    f"[ranking] weights {name} must be a number, not {w[name]!r}."
                )
        try:
            kwargs["ranking_weights"] = RankingWeights(
                **{
                    name: w[name]
                    for name in ("commits", "lines", "consistency", "recency")
                    if name in w
                }
            )
        except ValidationError as exc:
            # Pydantic's own text carries its input dump and a link to its site.
            errors = exc.errors()
            reasons = " ".join(
                f"{error['loc'][0]}: {error['msg']}."
                if error["loc"]
                else error["msg"].removeprefix("Value error, ")
                for error in errors
            )
            tail = (
                " Each weight must be a number between 0 and 1, and the four must sum to 1.0."
                if any(error["loc"] for error in errors)
                else ""
            )
            raise ConfigurationError(f"[ranking] weights is not valid: {reasons}{tail}") from exc
    return kwargs
