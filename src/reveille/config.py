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
from typing import Any, TypedDict, cast

from pydantic import BaseModel, Field, model_validator

from reveille.exceptions import ConfigurationError


class RankingWeights(BaseModel):
    """Configurable weights for the contributor ranking composite score.

    All four weights must sum to 1.0. Validation enforces this invariant
    at construction time.
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
            ValueError: If the sum deviates from 1.0 by more than 1e-9.
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
    ranking_enabled: bool = Field(default=True)
    ranking_weights: RankingWeights = Field(default_factory=RankingWeights)

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
    if "title" in report:
        kwargs["title"] = str(report["title"])
    if "output" in report:
        kwargs["output_path"] = Path(str(report["output"]))
    if "branch" in report:
        kwargs["branch"] = str(report["branch"])
    for field in ("since", "until"):
        if field in report:
            try:
                kwargs[field] = datetime.date.fromisoformat(str(report[field]))
            except ValueError as exc:
                raise ConfigurationError(
                    f"Invalid '{field}' date in configuration file: "
                    f"'{report[field]}'. Expected YYYY-MM-DD."
                ) from exc
    return kwargs


def _parse_filters_section(filters: dict[str, Any]) -> dict[str, Any]:
    """Parse the [filters] section of a Reveille TOML configuration file.

    Args:
        filters: The raw [filters] table from the parsed TOML document.

    Returns:
        A partial kwargs dict for ReportConfig construction.
    """
    kwargs: dict[str, Any] = {}
    if "min_commits" in filters:
        kwargs["min_commits"] = int(filters["min_commits"])
    if "exclude_authors" in filters:
        kwargs["exclude_authors"] = list(filters["exclude_authors"])
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
        kwargs["ranking_enabled"] = bool(ranking["enabled"])
    if "weights" in ranking:
        w = ranking["weights"]
        kwargs["ranking_weights"] = RankingWeights(
            commits=float(w.get("commits", 0.30)),
            lines=float(w.get("lines", 0.25)),
            consistency=float(w.get("consistency", 0.25)),
            recency=float(w.get("recency", 0.20)),
        )
    return kwargs
