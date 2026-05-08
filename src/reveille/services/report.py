"""Application service for report generation.

Orchestrates the full report generation pipeline:
    1. Validate the repository path.
    2. Read Git log data via the GitReader adapter.
    3. Derive the analysis window boundaries.
    4. Aggregate contributor statistics.
    5. Rank contributors using the ranking engine.
    6. Assemble the ReportData object.
    7. Render the HTML output via the Renderer adapter.
    8. Return the absolute path of the written file.

This layer has no direct knowledge of GitPython, Jinja2, Plotly,
or Typer. All external concerns are delegated to adapters.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from pathlib import Path

from reveille.adapters.git_reader import GitReader
from reveille.adapters.renderer import Renderer
from reveille.config import ReportConfig
from reveille.domain.models import RankedContributor, ReportData
from reveille.domain.ranking import rank_contributors


def generate_report(config: ReportConfig) -> Path:
    """Generate a self-contained HTML performance report.

    Args:
        config: Validated report configuration produced by the CLI layer.

    Returns:
        The absolute path of the written HTML file.

    Raises:
        RepositoryError: If the target path is not a readable Git repository.
        EmptyRepositoryError: If no commits exist within the analysis window.
        OutputPathError: If the output file cannot be written.
        RenderError: If the HTML template fails to render.
    """
    reader = GitReader(config.repo_path)

    commits = reader.read_commits(
        branch=config.branch,
        since=config.since,
        until=config.until,
        exclude_authors=config.exclude_authors,
    )

    window_start = (
        config.since if config.since is not None else min(c.timestamp.date() for c in commits)
    )
    window_end = config.until or datetime.date.today()

    contributor_stats = reader.aggregate_contributor_stats(
        commits=commits,
        min_commits=config.min_commits,
    )

    ranked_contributors: list[RankedContributor]
    if config.ranking_enabled and contributor_stats:
        ranked_contributors = rank_contributors(
            contributors=contributor_stats,
            commits=commits,
            weights=config.ranking_weights,
            window_start=window_start,
            window_end=window_end,
        )
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

    metadata = reader.read_metadata(
        total_commits=len(commits),
        unique_contributors=len(contributor_stats),
        analysis_since=window_start,
        analysis_until=window_end,
    )

    if config.title:
        metadata = replace(metadata, name=config.title)

    report_data = ReportData(
        metadata=metadata,
        ranked_contributors=ranked_contributors,
        commits=commits,
    )

    renderer = Renderer()
    return renderer.render(report_data, config.output_path, config.heatmap_granularity)
