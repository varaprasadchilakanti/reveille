# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Configuration model for Reveille report generation.

ReportConfig is the single validated input object passed from the
CLI layer to the application service. It is constructed from CLI
flags and an optional TOML configuration file, with CLI flags
taking precedence over file values in all cases.
"""

from __future__ import annotations

import datetime
import tomllib
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, Field, model_validator

from reveille.exceptions import ConfigurationError

OutputFormat = Literal["html", "json", "csv"]


class RankingWeights(BaseModel):
    """Configurable weights for the contributor ranking composite score.

    All four weights must sum to 1.0, so the composite score stays
    bounded to [0.0, 1.0] and remains comparable across runs. Validation
    enforces this at construction time.

    **The defaults are a judgement call, not an empirically derived
    model.** No study establishes that these four signals in this
    proportion measure anything in particular. They are documented here
    so the judgement can be argued with, and they are configurable so it
    can be overridden.

    The reasoning behind their relative ordering:

    - `commits` (0.30) is weighted highest because commit count is the
      most robust of the four. It is insensitive to file type, to
      generated code, and to how a change happens to be split across
      lines.
    - `lines` (0.25) captures volume, but is the easiest to distort:
      a vendored dependency, a lockfile, or a reformatting pass can
      dwarf months of considered work.
    - `consistency` (0.25) is active days over window days. It rewards
      sustained participation over a single burst, which is the closest
      any of these gets to a durability signal.
    - `recency` (0.20) is weighted lowest deliberately. Recency is a
      property of the analysis window rather than of the person; weight
      it higher and the same contributor's tier swings on the choice of
      end date.

    None of this makes the composite a measure of contribution. It
    measures volume and regularity of commits, which is what Git
    records. See `reveille.domain.ranking` for the caveat that belongs
    with any use of it.
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

    Constructed by the CLI layer from flag values and an optional TOML
    configuration file. Passed as-is to the application service layer.
    CLI flag values always take precedence over configuration file values.

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
    min_commits: int = Field(default=1, ge=1)
    # Off by default from 0.8.0. The ranking assigns named individuals a
    # composite score, a percentile and a military tier designation, and a
    # report that does that by default invites exactly the use its own
    # documentation says it must not be put to. Opt in with --ranking or
    # `[ranking] enabled = true`. See docs/adr/0010-ranking-is-opt-in.md.
    ranking_enabled: bool = Field(default=False)
    ranking_weights: RankingWeights = Field(default_factory=RankingWeights)
    output_format: OutputFormat = Field(default="html")
    deterministic: bool = Field(default=False)

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
    """Typed keyword-argument mapping for ReportConfig construction.

    All keys carry total=False because the dict is assembled incrementally:
    first from an optional TOML file, then from CLI flag overrides. Absent
    keys fall back to the ReportConfig field default at construction time.

    since and until are typed as datetime.date (not datetime.date | None)
    because when present in the mapping, the value is always a concrete
    date. The Optional annotation on ReportConfig expresses the
    absence-of-key default, not a stored None.
    """

    repo_path: Path
    output_path: Path
    title: str | None
    branch: str | None
    since: datetime.date
    until: datetime.date
    exclude_authors: list[str]
    min_commits: int
    ranking_enabled: bool
    ranking_weights: RankingWeights
    output_format: OutputFormat
    deterministic: bool


def load_config_from_toml(path: Path) -> ReportConfigKwargs:
    """Load and flatten configuration values from a Reveille TOML file.

    Reads the structured TOML format documented in the README and returns
    a typed keyword-argument mapping suitable for constructing a ReportConfig.
    Only keys present in the file are included — absent keys do not override
    CLI defaults.

    Args:
        path: Path to the TOML configuration file.

    Returns:
        A ReportConfigKwargs mapping of ReportConfig-compatible keyword arguments.

    Raises:
        ConfigurationError: If the file does not exist, cannot be read,
            is not valid TOML, or contains an invalid date string.
    """
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: '{path}'.") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Configuration file is not valid TOML: {exc}") from exc

    parts: dict[str, Any] = {}
    parts.update(_parse_report_section(raw.get("report", {})))
    parts.update(_parse_filters_section(raw.get("filters", {})))
    parts.update(_parse_ranking_section(raw.get("ranking", {})))
    return cast(ReportConfigKwargs, parts)


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
    # `str()` on a table or an array succeeds and produces nonsense: a title
    # of "{'a': 1}", or an output path of "[1, 2]", written out with exit 0.
    # The sibling type checks in `_parse_filters_section` exist for exactly
    # this reason; these three keys were missing them.
    for key, field in (("title", "title"), ("output", "output_path"), ("branch", "branch")):
        if key not in report:
            continue
        value = report[key]
        if not isinstance(value, str):
            raise ConfigurationError(
                f"Invalid '{key}' in the [report] section of the configuration "
                f"file: expected a string, got {type(value).__name__}."
            )
        kwargs[field] = Path(value) if field == "output_path" else value
    for field in ("since", "until"):
        if field in report:
            try:
                kwargs[field] = datetime.date.fromisoformat(str(report[field]))
            except ValueError as exc:
                raise ConfigurationError(
                    f"Invalid '{field}' date in configuration file: "
                    f"'{report[field]}'. Expected YYYY-MM-DD."
                ) from exc
    if "format" in report:
        kwargs["output_format"] = cast(OutputFormat, str(report["format"]))
    if "deterministic" in report:
        kwargs["deterministic"] = bool(report["deterministic"])
    return kwargs


def _parse_filters_section(filters: dict[str, Any]) -> dict[str, Any]:
    """Parse the [filters] section of a Reveille TOML configuration file.

    Args:
        filters: The raw [filters] table from the parsed TOML document.

    Returns:
        A partial kwargs dict for ReportConfig construction.

    Raises:
        ConfigurationError: If a value has the wrong type. These were bare
            `int()` and `list()` calls, so a mistyped key raised ValueError or
            TypeError, escaped the CLI's ConfigurationError handler, printed a
            traceback, and exited 1 -- which on this project's published
            contract means "ran correctly, negative answer" rather than "could
            not run".
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
        # A bare string would be split into characters by `list()`, silently
        # excluding contributors named "a", "b", "c" and nobody the user meant.
        if not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
            raise ConfigurationError(
                f"[filters] exclude_authors must be a list of strings, not {authors!r}."
            )
        kwargs["exclude_authors"] = list(authors)
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
        # Strict, not `bool(...)`. Any non-empty string is truthy, so
        # `enabled = "false"` would have switched the ranking ON -- and the
        # ranking is the one feature where an accidental enable names
        # individuals. A config that reads as "off" must never produce tiers.
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
        # Both arms matter. `float()` raises ValueError on a non-numeric
        # value, and RankingWeights raises pydantic's ValidationError when a
        # weight is out of range or the four do not sum to one. Neither was
        # caught, so a mistyped weight printed a raw traceback and exited 1 --
        # which on this project's published contract means "ran correctly,
        # negative answer" rather than "could not run".
        try:
            kwargs["ranking_weights"] = RankingWeights(
                commits=float(w.get("commits", 0.30)),
                lines=float(w.get("lines", 0.25)),
                consistency=float(w.get("consistency", 0.25)),
                recency=float(w.get("recency", 0.20)),
            )
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"[ranking] weights is not valid: {exc}. Each weight must be a "
                "number between 0 and 1, and the four must sum to 1.0."
            ) from exc
    return kwargs
