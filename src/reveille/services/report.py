"""Application service for report generation.

Orchestrates the full report generation pipeline:
    1. Validate the repository path and analysis window.
    2. Read Git log data via the git reader adapter.
    3. Pass contributor stats to the ranking engine.
    4. Pass ranked data to the renderer adapter.
    5. Return the path of the written HTML file.

This layer depends on domain models and adapter interfaces.
It has no direct knowledge of GitPython, Jinja2, Plotly, or Typer.
"""

from __future__ import annotations

from pathlib import Path

from reveille.config import ReportConfig


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

    Note:
        Full orchestration implementation scheduled for feat/report-renderer.
    """
    raise NotImplementedError(
        "generate_report is not yet implemented. "
        "Scheduled for feat/report-renderer."
    )
