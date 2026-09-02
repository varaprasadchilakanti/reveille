# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Application service for report generation.

Orchestrates the full report generation pipeline:
    1. Validate the repository path.
    2. Read Git log data via the GitReader adapter.
    3. Derive the analysis window boundaries.
    4. Aggregate contributor statistics.
    5. Rank contributors using the ranking engine.
    6. Assemble the ReportData object.
    7. Render to the configured format via the Renderer adapter --
       HTML, JSON, or CSV, dispatched on `config.output_format`.
    8. Return the absolute path of the written file.

This layer has no direct knowledge of GitPython, Jinja2, Plotly,
or Typer. All external concerns are delegated to adapters.

Progress is reported by emitting `ProgressEvent` objects to an optional
callback, not by writing to a terminal. Whether those events become an
animated spinner, log lines, or nothing at all is the CLI's decision;
the service holds no opinion about output devices.
"""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from reveille import __version__
from reveille.adapters.git_reader import GitReader
from reveille.adapters.renderer import Renderer
from reveille.config import ReportConfig
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    Commit,
    ProgressEvent,
    RankedContributor,
    ReportData,
)
from reveille.domain.ranking import rank_contributors

_logger = logging.getLogger(__name__)


def generate_report(
    config: ReportConfig,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> list[Path]:
    """Generate a self-contained HTML performance report.

    Args:
        config: Validated report configuration produced by the CLI layer.
        on_progress: Optional callable invoked with a ProgressEvent at each
            pipeline stage boundary. Carries the incoming stage label, elapsed
            time of the stage that just completed, and an optional item count.
            Has no effect on the output when omitted.

    Returns:
        The absolute path of the written HTML file.

    Raises:
        RepositoryError: If the target path is not a readable Git repository.
        EmptyRepositoryError: If no commits exist within the analysis window.
        OutputPathError: If the output file cannot be written.
        RenderError: If the HTML template fails to render.
    """
    _logger.debug("pipeline start: repo=%s", config.repo_path)
    reader = GitReader(config.repo_path)
    stage_start = time.monotonic()

    _emit(on_progress, "Reading commit history", 0.0)
    commits = reader.read_commits(
        branch=config.branch,
        since=config.since,
        until=config.until,
        exclude_authors=config.exclude_authors,
    )

    window_start = (
        config.since if config.since is not None else min(c.timestamp.date() for c in commits)
    )
    window_end = _resolve_window_end(config, commits)

    elapsed = time.monotonic() - stage_start
    stage_start = time.monotonic()

    _emit(on_progress, "Aggregating contributor statistics", elapsed, len(commits))
    contributor_stats = reader.aggregate_contributor_stats(
        commits=commits,
        min_commits=config.min_commits,
    )

    elapsed = time.monotonic() - stage_start
    stage_start = time.monotonic()

    ranked_contributors: list[RankedContributor]
    if config.ranking_enabled and contributor_stats:
        _emit(on_progress, "Ranking contributors", elapsed)
        ranked_contributors = rank_contributors(
            contributors=contributor_stats,
            commits=commits,
            weights=config.ranking_weights,
            window_start=window_start,
            window_end=window_end,
        )
        elapsed = time.monotonic() - stage_start
    else:
        ranked_contributors = [
            RankedContributor(
                stats=s,
                composite_score=0.0,
                percentile=0.0,
                tier=0,
                tier_designation="--",
            )
            for s in contributor_stats
        ]

    _emit(on_progress, "Rendering report", elapsed)

    metadata = reader.read_metadata(
        total_commits=len(commits),
        unique_contributors=len(contributor_stats),
        analysis_since=window_start,
        analysis_until=window_end,
        branch=config.branch,
    )
    if config.title:
        metadata = replace(metadata, name=config.title)

    head_sha = reader.resolve_head_sha(config.branch)

    # Deterministic mode pins the timestamp to the analysed commit, the way a
    # reproducible build pins to SOURCE_DATE_EPOCH: the value stays meaningful
    # and stops being a function of when the command happened to run.
    if config.deterministic:
        head_commit_time = max(c.timestamp for c in commits)
        metadata = replace(metadata, generated_at=head_commit_time)

    provenance = _build_provenance(config, head_sha, reader.mailmap_applied)

    report_data = ReportData(
        metadata=metadata,
        provenance=provenance,
        ranked_contributors=ranked_contributors,
        commits=commits,
    )

    _logger.debug(
        "assembled report data: %d commits, %d contributors",
        len(commits),
        len(contributor_stats),
    )
    renderer = Renderer()
    paths: list[Path] = []
    if config.output_format == "html":
        paths.append(renderer.render(report_data, config.output_path))
    if config.output_format == "json":
        paths.append(renderer.render_json(report_data, config.output_path.with_suffix(".json")))
    if config.output_format == "csv":
        paths.append(renderer.render_csv(report_data, config.output_path.with_suffix(".csv")))
    _logger.debug("wrote %d output file(s): %s", len(paths), [str(p) for p in paths])
    return paths


def _emit(
    on_progress: Callable[[ProgressEvent], None] | None,
    stage: str,
    elapsed_seconds: float,
    items_processed: int | None = None,
) -> None:
    """Emit a progress event if anybody is listening.

    Collapses the `if on_progress is not None` guard that otherwise repeats at
    every stage boundary. The service holds no opinion about output devices --
    whether these become a spinner, log lines, or nothing at all is the CLI's
    decision.

    Args:
        on_progress: The optional callback supplied by the caller.
        stage: Label of the stage now starting.
        elapsed_seconds: Duration of the stage that just completed.
        items_processed: Optional item count from the completed stage.
    """
    if on_progress is None:
        return
    on_progress(
        ProgressEvent(
            stage=stage,
            elapsed_seconds=elapsed_seconds,
            items_processed=items_processed,
        )
    )


def _resolve_window_end(config: ReportConfig, commits: list[Commit]) -> datetime.date:
    """Decide the closing date of the analysis window.

    In deterministic mode the window must close on something the repository
    itself determines. `date.today()` is an input from outside the repository
    and it feeds the recency component of the ranking, so without this two runs
    over an identical repository on different days produce different scores --
    and the output is not reproducible in any useful sense.

    Args:
        config: The validated report configuration.
        commits: The commits inside the window, used only for their timestamps.

    Returns:
        An explicit `--until` if given, otherwise the last commit date in
        deterministic mode, otherwise today.
    """
    if config.until is not None:
        return config.until
    if config.deterministic:
        return max(c.timestamp.date() for c in commits)
    return datetime.date.today()


def _build_provenance(
    config: ReportConfig,
    head_sha: str | None,
    mailmap_applied: bool,
) -> AnalysisProvenance:
    """Record what produced this report, and over what.

    Filters are recorded as *requested*, not as resolved. `analysis_since` says
    where the window began; `requested_since` says whether anybody asked for
    that, and only the pair distinguishes a filtered report from an unfiltered
    one that happens to start on the same date.

    Args:
        config: The validated report configuration.
        head_sha: SHA at the tip of the analysed ref, or None if unresolvable.
        mailmap_applied: Whether a non-empty `.mailmap` was applied.

    Returns:
        A populated AnalysisProvenance instance.
    """
    return AnalysisProvenance(
        reveille_version=__version__,
        schema_version=SCHEMA_VERSION,
        head_sha=head_sha,
        requested_branch=config.branch,
        requested_since=config.since,
        requested_until=config.until,
        exclude_authors=tuple(config.exclude_authors),
        min_commits=config.min_commits,
        ranking_enabled=config.ranking_enabled,
        # Reporting weights that were never applied would be a false statement.
        ranking_weights=(config.ranking_weights.model_dump() if config.ranking_enabled else None),
        mailmap_applied=mailmap_applied,
        deterministic=config.deterministic,
    )
