r"""HTML report renderer adapter.

Combines Jinja2 templating with Plotly chart generation to produce
a single self-contained HTML file. All JavaScript, CSS, and chart
data are embedded inline. The output requires no internet connection.

Chart rendering strategy: each chart is serialised as a Plotly JSON
specification and embedded in the document as an application/json
script block. Client-side initialisation renders all charts via
Plotly.newPlot() at page load, applying the active colour theme at
that time. On theme toggle, Plotly.relayout() updates each chart's
background, axis, and font properties without re-fetching trace data.
This strategy supports complete dark mode parity for all charts
without doubling the embedded payload.

The string "</script>" is escaped as "<\/script>" in all JSON
output to prevent premature script block termination when chart
labels or commit messages contain that sequence.
"""

from __future__ import annotations

import datetime
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, TypeAlias

import plotly.graph_objects as go
import plotly.offline
from jinja2 import Environment, PackageLoader, select_autoescape

from reveille.domain.models import Commit, RankedContributor, ReportData
from reveille.exceptions import OutputPathError, RenderError

HeatmapGranularity: TypeAlias = Literal["weekly", "monthly", "yearly"]

# Maximum individual slices in a pie chart. Contributors beyond this
# threshold are aggregated into a single "Other Contributors" slice
# to maintain readability at standard browser zoom levels.
_PIE_MAX_SLICES: int = 8

# Mid-brightness palette distinguishable on both light and dark backgrounds.
_PIE_PALETTE: list[str] = [
    "#3b82f6",
    "#14b8a6",
    "#22c55e",
    "#a855f7",
    "#f59e0b",
    "#06b6d4",
    "#ec4899",
    "#84cc16",
    "#6366f1",
    "#f97316",
]


# Module-level cache for the Plotly JS bundle.
# plotly.offline.get_plotlyjs() reads ~3.5 MB of minified JavaScript from
# disk on every call. Caching at module load time means each worker process
# pays the cost once, regardless of how many reports are rendered in that
# process. This is the primary driver of e2e test suite runtime.
_PLOTLY_JS_BUNDLE: str = plotly.offline.get_plotlyjs()


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

    def render(
        self,
        data: ReportData,
        output_path: Path,
        heatmap_granularity: HeatmapGranularity = "monthly",
    ) -> Path:
        """Render the report and write it to the specified output path.

        Args:
            data: The complete structured report dataset.
            output_path: Destination path for the HTML file.
            heatmap_granularity: Resolution of the commit activity heatmap.
                'weekly' renders one column per calendar week. 'monthly'
                renders one column per calendar month with weekday rows.
                'yearly' renders one column per year with month rows.
                Defaults to 'monthly', which balances detail and readability
                for repositories with more than six months of history.

        Returns:
            The absolute path of the written file.

        Raises:
            OutputPathError: If the parent directory does not exist or
                the file cannot be written.
            RenderError: If the Jinja2 template raises an error during rendering.
        """
        resolved = output_path.resolve()
        if not resolved.parent.exists():
            raise OutputPathError(
                f"Output directory '{resolved.parent}' does not exist. "
                "Create the directory before generating a report."
            )

        try:
            charts = self._build_charts(data, heatmap_granularity)
            derived = self._compute_derived_stats(data)
            plotly_js = _PLOTLY_JS_BUNDLE
            generated_at = data.metadata.generated_at.strftime("%Y-%m-%d %H:%M UTC")
            html = self._template.render(
                data=data,
                charts=charts,
                derived=derived,
                plotly_js=plotly_js,
                generated_at=generated_at,
                heatmap_granularity=heatmap_granularity,
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
            A dict of derived metric names to values for template use.
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

    def _build_charts(
        self,
        data: ReportData,
        heatmap_granularity: HeatmapGranularity,
    ) -> dict[str, str]:
        """Build all chart JSON specifications for the report.

        Each returned value is a Plotly figure serialised as a JSON string,
        suitable for embedding in an application/json script block and
        rendered client-side via Plotly.newPlot(). Returns the JSON
        string 'null' for any chart that lacks sufficient data.

        Args:
            data: The complete report dataset.
            heatmap_granularity: Resolution for the activity heatmap.

        Returns:
            A dict mapping chart identifier to Plotly JSON specification string.
        """
        return {
            "timeline": _build_timeline_chart(data.commits),
            "heatmap": _build_heatmap_chart(data.commits, heatmap_granularity),
            "contributor_commits": _build_contributor_commits_chart(
                data.ranked_contributors
            ),
            "contributor_lines": _build_contributor_lines_chart(
                data.ranked_contributors
            ),
            "pie_commits": _build_commit_share_pie(data.ranked_contributors),
            "pie_lines": _build_lines_share_pie(data.ranked_contributors),
        }


# ------------------------------------------------------------------
# Chart construction functions
# ------------------------------------------------------------------


def _build_timeline_chart(commits: list[Commit]) -> str:
    """Build a weekly commit frequency line chart.

    Args:
        commits: All commits in the analysis window.

    Returns:
        A Plotly figure JSON string, or 'null' if commits is empty.
    """
    if not commits:
        return "null"

    weekly: dict[str, int] = defaultdict(int)
    for commit in commits:
        d = commit.timestamp.date()
        week_start = d - datetime.timedelta(days=d.weekday())
        weekly[week_start.isoformat()] += 1

    sorted_weeks = sorted(weekly.keys())
    counts = [weekly[w] for w in sorted_weeks]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sorted_weeks,
            y=counts,
            mode="lines",
            fill="tozeroy",
            line={"color": "#3b82f6", "width": 2},
            fillcolor="rgba(59, 130, 246, 0.10)",
            hovertemplate="Week of %{x}<br>Commits: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        **_base_layout(),
        xaxis_title="Week",
        yaxis_title="Commits",
        height=280,
    )
    return _to_json(fig)


def _build_heatmap_chart(
    commits: list[Commit],
    granularity: HeatmapGranularity,
) -> str:
    """Build a commit activity heatmap at the specified granularity.

    Dispatches to the appropriate granularity-specific builder. Each
    builder produces a heatmap with a different time bucketing strategy
    suited to the volume of history being visualised.

    Args:
        commits: All commits in the analysis window.
        granularity: One of 'weekly', 'monthly', or 'yearly'.

    Returns:
        A Plotly figure JSON string, or 'null' if commits is empty.
    """
    if not commits:
        return "null"
    if granularity == "weekly":
        return _build_heatmap_weekly(commits)
    if granularity == "monthly":
        return _build_heatmap_monthly(commits)
    return _build_heatmap_yearly(commits)


def _build_heatmap_weekly(commits: list[Commit]) -> str:
    """Build a calendar-style weekly heatmap.

    Rows represent days of the week (Monday to Sunday). Columns represent
    calendar weeks across the analysis window. Best suited for repositories
    with fewer than six months of history.

    Args:
        commits: All commits in the analysis window. Must be non-empty.

    Returns:
        A Plotly figure JSON string.
    """
    earliest = min(c.timestamp.date() for c in commits)
    base_week = earliest - datetime.timedelta(days=earliest.weekday())
    cell: dict[tuple[int, int], int] = defaultdict(int)
    week_indices: set[int] = set()

    for commit in commits:
        d = commit.timestamp.date()
        week_start = d - datetime.timedelta(days=d.weekday())
        week_idx = (week_start - base_week).days // 7
        cell[(week_idx, d.weekday())] += 1
        week_indices.add(week_idx)

    num_weeks = max(week_indices) + 1
    z = [[cell.get((w, day), 0) for w in range(num_weeks)] for day in range(7)]
    week_labels = [
        (base_week + datetime.timedelta(weeks=w)).strftime("%b %d")
        for w in range(num_weeks)
    ]
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=week_labels,
            y=day_labels,
            colorscale=_heatmap_colorscale(),
            showscale=True,
            hovertemplate="Week: %{x}<br>Day: %{y}<br>Commits: %{z}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["xaxis"] = {
        "type": "category",
        "gridcolor": "#30363d",
        "linecolor": "#30363d",
    }
    layout["yaxis"] = {
        "autorange": "reversed",
        "gridcolor": "#30363d",
        "scaleanchor": "x",
        "constrain": "domain",
    }
    fig.update_layout(**layout, height=260)
    return _to_json(fig)


def _build_heatmap_monthly(commits: list[Commit]) -> str:
    """Build a monthly commit activity heatmap.

    Rows represent days of the week (Monday to Sunday). Columns represent
    calendar months labelled as YYYY-MM. Each cell contains the total
    commit count for that weekday across all occurrences within that
    calendar month. Suitable for repositories with six months to three
    years of history.

    Args:
        commits: All commits in the analysis window. Must be non-empty.

    Returns:
        A Plotly figure JSON string.
    """
    cell: dict[tuple[str, int], int] = defaultdict(int)
    months_set: set[str] = set()

    for commit in commits:
        d = commit.timestamp.date()
        month_key = f"{d.year:04d}-{d.month:02d}"
        cell[(month_key, d.weekday())] += 1
        months_set.add(month_key)

    sorted_months = sorted(months_set)
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    z = [[cell.get((month, day), 0) for month in sorted_months] for day in range(7)]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=sorted_months,
            y=day_labels,
            colorscale=_heatmap_colorscale(),
            showscale=True,
            hovertemplate="Month: %{x}<br>Day: %{y}<br>Commits: %{z}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["xaxis"] = {
        "type": "category",
        "gridcolor": "#30363d",
        "linecolor": "#30363d",
    }
    layout["yaxis"] = {
        "autorange": "reversed",
        "gridcolor": "#30363d",
        "scaleanchor": "x",
        "constrain": "domain",
    }
    fig.update_layout(**layout, height=260)
    return _to_json(fig)


def _build_heatmap_yearly(commits: list[Commit]) -> str:
    """Build a yearly commit activity heatmap.

    Rows represent months of the year (January to December). Columns
    represent calendar years. Each cell contains the total commit count
    for that month-year combination. Suitable for repositories with more
    than three years of history.

    Args:
        commits: All commits in the analysis window. Must be non-empty.

    Returns:
        A Plotly figure JSON string.
    """
    cell: dict[tuple[int, int], int] = defaultdict(int)
    years_set: set[int] = set()

    for commit in commits:
        d = commit.timestamp.date()
        cell[(d.year, d.month)] += 1
        years_set.add(d.year)

    sorted_years = sorted(years_set)
    month_labels = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    z = [
        [cell.get((year, month + 1), 0) for year in sorted_years] for month in range(12)
    ]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[str(y) for y in sorted_years],
            y=month_labels,
            colorscale=_heatmap_colorscale(),
            showscale=True,
            hovertemplate="Year: %{x}<br>Month: %{y}<br>Commits: %{z}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["xaxis"] = {
        "type": "category",
        "gridcolor": "#30363d",
        "linecolor": "#30363d",
    }
    layout["yaxis"] = {
        "autorange": "reversed",
        "gridcolor": "#30363d",
        "scaleanchor": "x",
        "constrain": "domain",
    }
    fig.update_layout(**layout, height=340)
    return _to_json(fig)


def _build_contributor_commits_chart(ranked: list[RankedContributor]) -> str:
    """Build a horizontal bar chart of commit counts per contributor.

    Contributors are ordered by rank, with the highest-ranked contributor
    at the top of the chart.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        A Plotly figure JSON string, or 'null' if ranked is empty.
    """
    if not ranked:
        return "null"

    names = [r.stats.name for r in reversed(ranked)]
    counts = [r.stats.commit_count for r in reversed(ranked)]
    tiers = [r.tier_designation for r in reversed(ranked)]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=names,
            orientation="h",
            marker_color="#3b82f6",
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
    return _to_json(fig)


def _build_contributor_lines_chart(ranked: list[RankedContributor]) -> str:
    """Build a grouped bar chart of lines added and deleted per contributor.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        A Plotly figure JSON string, or 'null' if ranked is empty.
    """
    if not ranked:
        return "null"

    names = [r.stats.name for r in ranked]
    added = [r.stats.lines_added for r in ranked]
    deleted = [r.stats.lines_deleted for r in ranked]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Lines Added",
            x=names,
            y=added,
            marker_color="#10b981",
            hovertemplate="%{x}<br>Added: %{y:,}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Lines Deleted",
            x=names,
            y=deleted,
            marker_color="#f87171",
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
    return _to_json(fig)


def _build_commit_share_pie(ranked: list[RankedContributor]) -> str:
    """Build a donut chart showing each contributor's share of total commits.

    Contributors beyond _PIE_MAX_SLICES are aggregated into a single
    'Other Contributors' slice to maintain legibility.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        A Plotly figure JSON string, or 'null' if fewer than two contributors
        are present. A single-contributor pie carries no comparative information.
    """
    if len(ranked) < 2:
        return "null"

    sorted_r = sorted(ranked, key=lambda r: r.stats.commit_count, reverse=True)
    labels, values = _aggregate_pie_data(
        [(r.stats.name, r.stats.commit_count) for r in sorted_r]
    )

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            textposition="outside",
            textinfo="label+percent",
            marker={"colors": _pie_colors(len(labels))},
            hovertemplate="%{label}<br>Commits: %{value:,}<br>%{percent}<extra></extra>",
            sort=False,
        )
    )
    layout = _base_layout()
    layout["showlegend"] = False
    layout["margin"] = {"l": 20, "r": 20, "t": 20, "b": 20}
    fig.update_layout(**layout, height=320)
    return _to_json(fig)


def _build_lines_share_pie(ranked: list[RankedContributor]) -> str:
    """Build a donut chart showing each contributor's share of total lines changed.

    Lines changed is additions plus deletions, providing a volume measure
    of code activity independent of the net direction of change.
    Contributors beyond _PIE_MAX_SLICES are aggregated.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        A Plotly figure JSON string, or 'null' if fewer than two contributors
        are present.
    """
    if len(ranked) < 2:
        return "null"

    sorted_r = sorted(ranked, key=lambda r: r.stats.lines_changed, reverse=True)
    labels, values = _aggregate_pie_data(
        [(r.stats.name, r.stats.lines_changed) for r in sorted_r]
    )

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            textposition="outside",
            textinfo="label+percent",
            marker={"colors": _pie_colors(len(labels))},
            hovertemplate="%{label}<br>Lines: %{value:,}<br>%{percent}<extra></extra>",
            sort=False,
        )
    )
    layout = _base_layout()
    layout["showlegend"] = False
    layout["margin"] = {"l": 20, "r": 20, "t": 20, "b": 20}
    fig.update_layout(**layout, height=320)
    return _to_json(fig)


# ------------------------------------------------------------------
# Derived metric helpers
# ------------------------------------------------------------------


def _compute_bus_factor(ranked: list[RankedContributor]) -> int:
    """Compute the bus factor for the contributor population.

    The bus factor is the minimum number of contributors whose combined
    commit volume accounts for at least 50 percent of total commits.
    A lower value indicates higher concentration risk.

    Args:
        ranked: Ranked contributor list.

    Returns:
        An integer in the range [1, len(ranked)]. Returns 0 if ranked is empty.
    """
    if not ranked:
        return 0
    total = sum(r.stats.commit_count for r in ranked)
    if total == 0:
        return 0
    threshold = total * 0.5
    sorted_by_commits = sorted(ranked, key=lambda r: r.stats.commit_count, reverse=True)
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
    which no commits were recorded.

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
# Chart helper utilities
# ------------------------------------------------------------------


def _aggregate_pie_data(
    items: list[tuple[str, int]],
) -> tuple[list[str], list[int]]:
    """Aggregate ranked (label, value) pairs for pie chart rendering.

    Items beyond _PIE_MAX_SLICES are summed into a trailing slice
    labelled 'Other Contributors'. The input order is preserved because
    the Pie trace uses sort=False.

    Args:
        items: (label, value) pairs, sorted by value descending by the caller.

    Returns:
        A tuple of (labels, values) lists of equal length.
    """
    if len(items) <= _PIE_MAX_SLICES:
        return [i[0] for i in items], [i[1] for i in items]

    top = items[:_PIE_MAX_SLICES]
    others_total = sum(i[1] for i in items[_PIE_MAX_SLICES:])
    labels = [i[0] for i in top] + ["Other Contributors"]
    values = [i[1] for i in top] + [others_total]
    return labels, values


def _pie_colors(n: int) -> list[str]:
    """Return n colours from the professional palette, cycling if necessary.

    Args:
        n: Number of colours required.

    Returns:
        A list of n hex colour strings.
    """
    return [_PIE_PALETTE[i % len(_PIE_PALETTE)] for i in range(n)]


def _heatmap_colorscale() -> list[list[float | str]]:
    """Return the Plotly colorscale for all heatmap variants.

    Zero-value cells are fully transparent, which renders as the page
    background colour in both light and dark modes without requiring
    a separate theme-specific colorscale.

    Returns:
        A list of [position, colour] pairs in Plotly colorscale format.
    """
    return [
        [0.0, "rgba(0, 0, 0, 0)"],
        [0.001, "#bfdbfe"],
        [0.35, "#3b82f6"],
        [1.0, "#1e3a8a"],
    ]


# ------------------------------------------------------------------
# Layout helpers
# ------------------------------------------------------------------


def _base_layout() -> dict[str, Any]:
    """Return shared Plotly layout configuration for all charts.

    Background colours and font colour are intentionally absent. They
    are injected by the client-side theme manager at render time via
    Plotly.relayout(), allowing charts to respond correctly to
    dark/light mode toggles without re-fetching trace data.

    Returns:
        A dict of Plotly layout keyword arguments.
    """
    return {
        "font": {
            "family": (
                "-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                "Roboto, 'Helvetica Neue', Arial, sans-serif"
            ),
            "size": 12,
        },
        "margin": {"l": 60, "r": 30, "t": 20, "b": 50},
        "xaxis": {"gridcolor": "#e2e8f0", "linecolor": "#d1d9e0"},
        "yaxis": {"gridcolor": "#e2e8f0", "linecolor": "#d1d9e0"},
        "showlegend": False,
        "modebar": {"remove": ["logo"]},
    }


def _to_json(fig: go.Figure) -> str:
    r"""Serialise a Plotly figure to a JSON specification string.

    Background colours (paper_bgcolor, plot_bgcolor) and font colour are
    stripped from the layout before serialisation. These are injected by
    the client-side theme manager at render time.

    The sequence "</" is escaped as "<\/" throughout the output to prevent
    any "</script>" in label text from terminating the embedding script block.

    Args:
        fig: A fully configured Plotly Figure instance.

    Returns:
        A JSON string containing 'data' and 'layout' keys.
    """
    figure_json: str = fig.to_json() or "{}"
    raw: dict[str, Any] = json.loads(figure_json)
    layout = raw.get("layout", {})
    for key in ("paper_bgcolor", "plot_bgcolor"):
        layout.pop(key, None)
    if "font" in layout:
        layout["font"].pop("color", None)
    raw["layout"] = layout
    return json.dumps(raw).replace("</", "<\\/")
