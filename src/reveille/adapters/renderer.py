"""HTML report renderer adapter.

Combines Jinja2 templating with Plotly chart generation to produce
a single self-contained HTML file. All JavaScript, CSS, and chart
data are embedded inline. The output requires no internet connection.

Chart generation follows a single-bundle strategy: the Plotly JavaScript
library is embedded once in the document head, and all chart divs are
rendered with include_plotlyjs=False to avoid duplication. This keeps
the output self-contained while minimising redundant payload.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import plotly.offline
from jinja2 import Environment, PackageLoader, select_autoescape

from reveille.domain.models import Commit, RankedContributor, ReportData
from reveille.exceptions import OutputPathError, RenderError


class Renderer:
    """Renders a ReportData instance into a self-contained HTML file."""

    def __init__(self) -> None:
        """Load the Jinja2 environment and validate the template is present.

        Raises:
            RenderError: If the report template cannot be located within
                the installed package.
        """
        try:
            self._env = Environment(
                loader=PackageLoader("reveille", "templates"),
                autoescape=select_autoescape(["html", "j2"]),
            )
            self._template = self._env.get_template("report.html.j2")
        except Exception as exc:
            raise RenderError(
                "Failed to load the report template. "
                "Verify the package was installed correctly and that "
                "src/reveille/templates/report.html.j2 exists."
            ) from exc

    def render(self, data: ReportData, output_path: Path) -> Path:
        """Render the report and write it to the specified output path.

        Args:
            data: The complete structured report dataset.
            output_path: Destination path for the HTML file.

        Returns:
            The absolute path of the written file.

        Raises:
            OutputPathError: If the parent directory does not exist or
                the file cannot be written.
            RenderError: If the Jinja2 template raises an error.
        """
        resolved = output_path.resolve()
        if not resolved.parent.exists():
            raise OutputPathError(
                f"Output directory '{resolved.parent}' does not exist. "
                "Create the directory before generating a report."
            )

        try:
            charts = self._build_charts(data)
            derived = self._compute_derived_stats(data)
            plotly_js = plotly.offline.get_plotlyjs()
            generated_at = data.metadata.generated_at.strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            html = self._template.render(
                data=data,
                charts=charts,
                derived=derived,
                plotly_js=plotly_js,
                generated_at=generated_at,
            )
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"Template rendering failed: {exc}") from exc

        try:
            resolved.write_text(html, encoding="utf-8")
        except OSError as exc:
            raise OutputPathError(
                f"Failed to write report to '{resolved}': {exc}"
            ) from exc

        return resolved

    # ------------------------------------------------------------------
    # Derived statistics
    # ------------------------------------------------------------------

    def _compute_derived_stats(self, data: ReportData) -> dict[str, object]:
        """Compute summary statistics not stored on the domain models.

        Args:
            data: The complete report dataset.

        Returns:
            A dict of derived metric names to values for use in the template.
        """
        return {
            "bus_factor": _compute_bus_factor(data.ranked_contributors),
            "longest_inactive_streak": _compute_longest_inactive_streak(
                data.commits,
                data.metadata.analysis_since,
                data.metadata.analysis_until,
            ),
        }

    # ------------------------------------------------------------------
    # Chart builders
    # ------------------------------------------------------------------

    def _build_charts(self, data: ReportData) -> dict[str, str]:
        """Build all chart HTML strings for the report.

        Args:
            data: The complete report dataset.

        Returns:
            A dict mapping chart name to HTML string (div only, no script).
        """
        return {
            "timeline": _build_timeline_chart(data.commits),
            "heatmap": _build_heatmap_chart(data.commits),
            "contributor_commits": _build_contributor_commits_chart(
                data.ranked_contributors
            ),
            "contributor_lines": _build_contributor_lines_chart(
                data.ranked_contributors
            ),
        }


# ------------------------------------------------------------------
# Chart construction functions
# ------------------------------------------------------------------

def _build_timeline_chart(commits: list[Commit]) -> str:
    """Build a weekly commit frequency line chart.

    Args:
        commits: All commits in the analysis window.

    Returns:
        An HTML string containing a Plotly div with no script tags.
    """
    if not commits:
        return "<p class='chart-empty'>No commit data available.</p>"

    weekly: dict[datetime.date, int] = defaultdict(int)
    for commit in commits:
        d = commit.timestamp.date()
        week_start = d - datetime.timedelta(days=d.weekday())
        weekly[week_start] += 1

    sorted_weeks = sorted(weekly.keys())
    counts = [weekly[w] for w in sorted_weeks]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sorted_weeks,
            y=counts,
            mode="lines",
            fill="tozeroy",
            line={"color": "#1e40af", "width": 2},
            fillcolor="rgba(30, 64, 175, 0.08)",
            hovertemplate="Week of %{x}<br>Commits: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        **_base_layout(),
        xaxis_title="Week",
        yaxis_title="Commits",
        height=280,
    )
    return _to_html(fig)


def _build_heatmap_chart(commits: list[Commit]) -> str:
    """Build a calendar-style commit activity heatmap.

    Rows represent days of the week (Monday to Sunday).
    Columns represent calendar weeks across the analysis window.

    Args:
        commits: All commits in the analysis window.

    Returns:
        An HTML string containing a Plotly div with no script tags.
    """
    if not commits:
        return "<p class='chart-empty'>No commit data available.</p>"

    earliest = min(c.timestamp.date() for c in commits)
    base_week = earliest - datetime.timedelta(days=earliest.weekday())
    cell: dict[tuple[int, int], int] = defaultdict(int)
    week_indices: set[int] = set()

    for commit in commits:
        d = commit.timestamp.date()
        week_start = d - datetime.timedelta(days=d.weekday())
        week_idx = (week_start - base_week).days // 7
        day_idx = d.weekday()
        cell[(week_idx, day_idx)] += 1
        week_indices.add(week_idx)

    num_weeks = max(week_indices) + 1
    z = [
        [cell.get((w, day), 0) for w in range(num_weeks)]
        for day in range(7)
    ]
    week_labels = [
        (base_week + datetime.timedelta(weeks=w)).isoformat()
        for w in range(num_weeks)
    ]
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=week_labels,
            y=day_labels,
            colorscale=[
                [0.0, "#f1f5f9"],
                [0.001, "#bfdbfe"],
                [0.35, "#3b82f6"],
                [1.0, "#1e3a8a"],
            ],
            showscale=True,
            hovertemplate="Week: %{x}<br>Day: %{y}<br>Commits: %{z}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["yaxis"] = {"autorange": "reversed", "gridcolor": "#e2e8f0"}
    fig.update_layout(**layout, height=260)
    return _to_html(fig)


def _build_contributor_commits_chart(ranked: list[RankedContributor]) -> str:
    """Build a horizontal bar chart of commit counts per contributor.

    Contributors are ordered by rank, with the highest-ranked contributor
    at the top of the chart.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        An HTML string containing a Plotly div with no script tags.
    """
    if not ranked:
        return "<p class='chart-empty'>No contributor data available.</p>"

    names = [r.stats.name for r in reversed(ranked)]
    counts = [r.stats.commit_count for r in reversed(ranked)]
    tiers = [r.tier_designation for r in reversed(ranked)]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=names,
            orientation="h",
            marker_color="#1e40af",
            customdata=tiers,
            hovertemplate="%{y}<br>Commits: %{x}<br>Tier: %{customdata}<extra></extra>",
            text=[str(c) for c in counts],
            textposition="outside",
        )
    )
    fig.update_layout(
        **_base_layout(),
        xaxis_title="Commits",
        height=max(280, len(ranked) * 44 + 80),
    )
    return _to_html(fig)


def _build_contributor_lines_chart(ranked: list[RankedContributor]) -> str:
    """Build a grouped bar chart of lines added and deleted per contributor.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        An HTML string containing a Plotly div with no script tags.
    """
    if not ranked:
        return "<p class='chart-empty'>No contributor data available.</p>"

    names = [r.stats.name for r in ranked]
    added = [r.stats.lines_added for r in ranked]
    deleted = [r.stats.lines_deleted for r in ranked]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Lines Added",
            x=names,
            y=added,
            marker_color="#059669",
            hovertemplate="%{x}<br>Added: %{y:,}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Lines Deleted",
            x=names,
            y=deleted,
            marker_color="#dc2626",
            hovertemplate="%{x}<br>Deleted: %{y:,}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["showlegend"] = True
    fig.update_layout(
        **layout,
        barmode="group",
        yaxis_title="Lines",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        height=340,
    )
    return _to_html(fig)


# ------------------------------------------------------------------
# Derived metric helpers
# ------------------------------------------------------------------

def _compute_bus_factor(ranked: list[RankedContributor]) -> int:
    """Compute the bus factor for the contributor population.

    The bus factor is the minimum number of contributors whose combined
    commit volume accounts for at least 50% of total commits. A lower
    value indicates higher concentration risk.

    Args:
        ranked: Ranked contributor list.

    Returns:
        An integer in the range [1, len(ranked)].
    """
    if not ranked:
        return 0
    total = sum(r.stats.commit_count for r in ranked)
    if total == 0:
        return 0
    threshold = total * 0.5
    sorted_by_commits = sorted(
        ranked, key=lambda r: r.stats.commit_count, reverse=True
    )
    cumulative = 0
    for i, contributor in enumerate(sorted_by_commits, start=1):
        cumulative += contributor.stats.commit_count
        if cumulative >= threshold:
            return i
    return len(ranked)


def _compute_longest_inactive_streak(
    commits: list[Commit],
    window_start: datetime.date,
    window_end: datetime.date,
) -> int:
    """Compute the longest consecutive inactive period in days.

    An inactive day is a calendar day within the analysis window on
    which no commits were recorded. The streak is the maximum number
    of consecutive such days.

    Args:
        commits: All commits in the analysis window.
        window_start: Start of the analysis window.
        window_end: End of the analysis window.

    Returns:
        The longest inactive streak in days. Zero if every day had a commit.
    """
    if not commits:
        return (window_end - window_start).days

    active_dates = {c.timestamp.date() for c in commits}
    longest = 0
    streak = 0
    current = window_start
    while current <= window_end:
        if current not in active_dates:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
        current += datetime.timedelta(days=1)
    return longest


# ------------------------------------------------------------------
# Layout helpers
# ------------------------------------------------------------------

def _base_layout() -> dict[str, Any]:
    """Return shared Plotly layout configuration for all charts.

    Enforces a consistent professional aesthetic: system font stack,
    white background, minimal gridlines, no Plotly logo or branding.

    Returns:
        A dict of Plotly layout keyword arguments.
    """
    return {
        "paper_bgcolor": "white",
        "plot_bgcolor": "#f8fafc",
        "font": {
            "family": (
                "-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                "Roboto, 'Helvetica Neue', Arial, sans-serif"
            ),
            "color": "#0f172a",
            "size": 12,
        },
        "margin": {"l": 60, "r": 30, "t": 20, "b": 50},
        "xaxis": {"gridcolor": "#e2e8f0", "linecolor": "#cbd5e1"},
        "yaxis": {"gridcolor": "#e2e8f0", "linecolor": "#cbd5e1"},
        "showlegend": False,
        "modebar": {"remove": ["logo"]},
    }


def _to_html(fig: go.Figure) -> str:
    """Serialise a Plotly figure to an HTML div string.

    The Plotly JS bundle is excluded because it is embedded once in the
    document head by the Jinja2 template. The div is configured as
    responsive to adapt to its container width.

    Args:
        fig: A fully configured Plotly Figure instance.

    Returns:
        An HTML string containing only the chart div element.
    """
    return fig.to_html(  # type: ignore[no-any-return]
        full_html=False,
        include_plotlyjs=False,
        config={
            "responsive": True,
            "displayModeBar": True,
            "displaylogo": False,
        },
    )
