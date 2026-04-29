"""Configuration model for Reveille report generation.

ReportConfig is the single validated input object passed from the
CLI layer to the application service. It is constructed from CLI
flags and an optional TOML configuration file, with CLI flags
taking precedence over file values in all cases.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


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
        if abs(total - 1.0) > 1e-9:
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
        if (
            self.since is not None
            and self.until is not None
            and self.since > self.until
        ):
            raise ValueError(
                f"since ({self.since}) must be earlier than until ({self.until})."
            )
        return self
