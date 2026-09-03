# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

r"""Report renderer adapter.

Renders `ReportData` to one of three formats. `render` produces the
HTML report; `render_json` and `render_csv` produce machine-readable
output for downstream tooling. This is the only layer in Reveille that
imports Jinja2 or Plotly.

The HTML path combines Jinja2 templating with Plotly chart generation
to produce a single self-contained file. All JavaScript, CSS, and chart
data are embedded inline. The output makes no network requests, which
is what makes it safe to forward to someone who will open it on an
unknown machine.

Chart rendering strategy: each chart is serialised as a Plotly JSON
specification and embedded in the document as an application/json
script block. Client-side initialisation renders all charts via
Plotly.newPlot() at page load, applying the active colour theme at
that time. On theme toggle, Plotly.relayout() updates each chart's
background, axis, and font properties without re-fetching trace data.

The activity heatmap uses a compact daily-count payload rather than
a pre-built Plotly spec. The client builds the GitHub-style 7-row
grid (Mon-Sun rows, calendar-week columns) from the raw counts,
allowing year and contributor navigation via Plotly.react() without
re-fetching data from the server.

The string "</script>" is escaped as "<\/script>" in all JSON
output to prevent premature script block termination when chart
labels or commit messages contain that sequence.
"""

from __future__ import annotations

import csv
import datetime
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import plotly.offline
from jinja2 import (
    Environment,
    PackageLoader,
    TemplateNotFound,
    TemplatesNotFound,
    select_autoescape,
)

from reveille.domain.concentration import gini_coefficient, lorenz_curve
from reveille.domain.models import (
    Commit,
    RankedContributor,
    ReportData,
)
from reveille.exceptions import OutputPathError, RenderError

# Maximum individual slices in a pie chart. Contributors beyond this
# threshold are aggregated into a single "Other Contributors" slice
# to maintain readability at standard browser zoom levels.
_PIE_MAX_SLICES: int = 8

# Label of the aggregated residual slice, referenced where its colour is chosen.
_OTHER_LABEL: str = "Other Contributors"

# Categorical palette, used wherever colour encodes *identity* -- one hue per
# contributor, in fixed order.
#
# These eight are a measured set, not a chosen one. The previous palette put
# #22c55e (green) next to #14b8a6 (teal) at a normal-vision perceptual distance
# of Delta-E 11.3, below the 15 floor at which two adjacent series stop being
# reliably separable by a reader with full colour vision -- and they were
# adjacent, so contributors ranked second and third were the pair that
# collided. It also failed for deuteranopia at the margins.
#
# This set was validated against both report surfaces before adoption:
# the light plot background (#f6f8fa) and the dark one (#161b22). Worst
# adjacent pair is Delta-E 19.3 normal vision and 8.4 under protanopia,
# clearing both floors in each mode -- which is why one palette can serve both
# themes and no colours need to change when the theme toggle is used.
#
# One slot sits just under a 3:1 contrast ratio on the light surface. That is
# permitted only because identity is never carried by colour alone here: every
# chart using these has a legend, the pies carry direct labels, and the
# contributor table restates the same figures as text.
_CATEGORICAL_PALETTE: list[str] = [
    "#3987e5",  # blue
    "#d95926",  # orange
    "#199e70",  # aqua
    "#c98500",  # yellow
    "#d55181",  # magenta
    "#008300",  # green
    "#9085e9",  # violet
    "#e66767",  # red
]

# Series colours are assigned in fixed order and never cycled. A ninth
# contributor does not get slot one again -- two people sharing a colour makes
# the chart state something false. Charts that could exceed the palette cap
# their series count instead; see _build_contributor_timeline_chart.
_MAX_SERIES: int = len(_CATEGORICAL_PALETTE)

# Added and deleted lines are a semantic pair, not two arbitrary categories, so
# they are named rather than taken from the categorical order. They are drawn
# from the same validated set to keep one visual language across the report.
_LINES_ADDED_COLOUR: str = "#008300"
_LINES_DELETED_COLOUR: str = "#e66767"

# The trailing "Other Contributors" slice is a residual, not an identity, so it
# gets a neutral rather than a hue from the categorical order. Without this the
# ninth slice wrapped around to slot one and shared a colour with the
# top-ranked contributor inside the same pie -- two different things drawn the
# same way, in the one chart where every slice is visible at once.
# Contrast: 3.89:1 on the light plot surface, 4.17:1 on the dark one.
_OTHER_SLICE_COLOUR: str = "#7d7d76"


def _translucent(hex_colour: str, alpha: float) -> str:
    """Return a `#rrggbb` colour as an `rgba(...)` string at the given alpha.

    Area fills were previously written out as literal `rgba(57, 135, 229, ...)`
    strings that happened to equal `_CATEGORICAL_PALETTE[0]`. Nothing coupled
    them, so a palette change -- and the palette was replaced wholesale in
    0.8.0 -- would have left a fill in the old hue under a line in the new one.

    Args:
        hex_colour: A colour in `#rrggbb` form.
        alpha: Opacity between 0.0 and 1.0.

    Returns:
        The equivalent CSS `rgba()` string.
    """
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


# Ceiling on a per-contributor bar chart. The height grew with the contributor
# count and nothing bounded it: 5,000 contributors produced a chart 220,080
# pixels tall, which no browser renders usefully. The bars compress past this
# point, which is a worse chart -- but a worse chart is not the same kind of
# problem as an unusable document.
_MAX_CHART_HEIGHT: int = 2400

# The Lorenz chart's reference diagonal. A reference line is not a series, so
# it takes the same neutral as the residual slice rather than a categorical hue
# -- it must read as scaffolding, not as a third contributor.
_EQUALITY_LINE_COLOUR: str = "#7d7d76"

# Pre-compiled patterns for sanitising user-controlled strings.
# _SCRIPT_BLOCK_RE removes script elements including their content before
# _HTML_TAG_RE strips remaining tags, preventing script body text from
# surviving as raw output after tag removal.
_SCRIPT_BLOCK_RE: re.Pattern[str] = re.compile(
    r"<script\b[^>]*>.*?</script\b[^>]*>", re.IGNORECASE | re.DOTALL
)
_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")

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
        except (TemplateNotFound, TemplatesNotFound, OSError) as exc:
            raise RenderError(
                "Failed to load the report template. "
                "Verify the package was installed correctly and that "
                "src/reveille/templates/report.html.j2 exists."
            ) from exc

    def render(
        self,
        data: ReportData,
        output_path: Path,
    ) -> Path:
        """Render the report and write it to the specified output path.

        Args:
            data: The complete structured report dataset.
            output_path: Destination path for the HTML file.

        Returns:
            The absolute path of the written file.

        Raises:
            OutputPathError: If the parent directory does not exist or
                the file cannot be written.
            RenderError: If the Jinja2 template raises an error during rendering.
        """
        _assert_not_symlink(output_path)
        resolved = output_path.resolve()
        if not resolved.parent.exists():
            raise OutputPathError(
                f"Output directory '{resolved.parent}' does not exist. "
                "Create the directory before generating a report."
            )

        try:
            charts = self._build_charts(data)
            derived = self._compute_derived_stats(data)
            plotly_js = _PLOTLY_JS_BUNDLE
            generated_at = data.metadata.generated_at.strftime("%Y-%m-%d %H:%M UTC")
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
            raise OutputPathError(f"Failed to write report to '{resolved}': {exc}") from exc

        return resolved

    def render_json(self, data: ReportData, output_path: Path) -> Path:
        """Serialise the report data to a structured JSON file.

        The payload contains repository metadata, ranked contributor statistics
        with all scoring fields, and derived health metrics. The raw commits
        list is excluded. Dates are ISO 8601 strings. Suitable for consumption
        by dashboards, data warehouses, and Jira integrations without parsing
        HTML.

        Args:
            data: The complete structured report dataset.
            output_path: Destination path for the JSON file.

        Returns:
            The absolute path of the written file.

        Raises:
            OutputPathError: If the parent directory does not exist or
                the file cannot be written.
        """
        _assert_not_symlink(output_path)
        resolved = output_path.resolve()
        if not resolved.parent.exists():
            raise OutputPathError(
                f"Output directory '{resolved.parent}' does not exist. "
                "Create the directory before generating a report."
            )

        derived = self._compute_derived_stats(data)

        payload: dict[str, Any] = {
            # First key in the document, deliberately: a consumer should be
            # able to decide whether it can parse the rest before it tries.
            "schema_version": data.provenance.schema_version,
            "metadata": {
                "name": data.metadata.name,
                "remote_url": data.metadata.remote_url,
                "analysed_branch": data.metadata.analysed_branch,
                "total_commits": data.metadata.total_commits,
                "unique_contributors": data.metadata.unique_contributors,
                "analysis_since": data.metadata.analysis_since.isoformat(),
                "analysis_until": data.metadata.analysis_until.isoformat(),
                "generated_at": data.metadata.generated_at.isoformat(),
            },
            # What produced these numbers, and over what. Two reports that
            # disagree can only be reconciled if each states its own inputs.
            "provenance": {
                "reveille_version": data.provenance.reveille_version,
                "head_sha": data.provenance.head_sha,
                "deterministic": data.provenance.deterministic,
                "mailmap_applied": data.provenance.mailmap_applied,
                "filters": {
                    "requested_branch": data.provenance.requested_branch,
                    "requested_since": (
                        data.provenance.requested_since.isoformat()
                        if data.provenance.requested_since
                        else None
                    ),
                    "requested_until": (
                        data.provenance.requested_until.isoformat()
                        if data.provenance.requested_until
                        else None
                    ),
                    "exclude_authors_count": data.provenance.exclude_authors_count,
                    "min_commits": data.provenance.min_commits,
                },
                "ranking": {
                    "enabled": data.provenance.ranking_enabled,
                    "weights": data.provenance.ranking_weights,
                },
            },
            "contributors": [
                {
                    "rank": i + 1,
                    "name": r.stats.name,
                    "email": r.stats.email,
                    # Ranking fields are omitted entirely when ranking is off,
                    # rather than emitted with sentinel values. A key carrying
                    # `"tier": 0` is a number a consumer can read as data; an
                    # absent key cannot be misread. `provenance.ranking.enabled`
                    # says which shape to expect.
                    **(
                        {
                            "tier": r.tier,
                            "tier_designation": r.tier_designation,
                            "composite_score": r.composite_score,
                            "percentile": r.percentile,
                        }
                        if data.provenance.ranking_enabled
                        else {}
                    ),
                    "commit_count": r.stats.commit_count,
                    "lines_added": r.stats.lines_added,
                    "lines_deleted": r.stats.lines_deleted,
                    "net_lines": r.stats.net_lines,
                    "lines_changed": r.stats.lines_changed,
                    "active_days": r.stats.active_days,
                    "first_commit_date": r.stats.first_commit_date.isoformat(),
                    "last_commit_date": r.stats.last_commit_date.isoformat(),
                }
                for i, r in enumerate(data.ranked_contributors)
            ],
            "derived": {
                "commit_concentration": derived["commit_concentration"],
                "gini_coefficient": derived["gini_coefficient"],
                "longest_inactive_streak": derived["longest_inactive_streak"],
            },
        }

        try:
            resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            raise OutputPathError(f"Failed to write JSON report to '{resolved}': {exc}") from exc

        return resolved

    def render_csv(self, data: ReportData, output_path: Path) -> Path:
        """Serialise the ranked contributor table to a UTF-8 CSV file with BOM encoding.

        BOM encoding ensures correct column rendering in Microsoft Excel on
        Windows without requiring a manual import wizard configuration.

        Args:
            data: The complete structured report dataset.
            output_path: Destination path for the CSV file.

        Returns:
            The absolute path of the written file.

        Raises:
            OutputPathError: If the parent directory does not exist or
                the file cannot be written.
        """
        _assert_not_symlink(output_path)
        resolved = output_path.resolve()
        if not resolved.parent.exists():
            raise OutputPathError(
                f"Output directory '{resolved.parent}' does not exist. "
                "Create the directory before generating a report."
            )

        # Ranking columns are omitted entirely when ranking is off, mirroring
        # render_json. Emitting `tier,0` and `composite_score,0.0` puts a number
        # a reader can sort on into the format most likely to be opened in a
        # spreadsheet -- which is exactly the reading ADR 0010 exists to prevent.
        # `rank` stays in both formats as the row ordinal; with ranking off the
        # rows are ordered by commit count.
        ranked = data.provenance.ranking_enabled
        fieldnames = [
            "rank",
            "name",
            "email",
            "commits",
            "lines_added",
            "lines_deleted",
            "net_lines",
            "active_days",
            "last_commit_date",
        ]
        if ranked:
            fieldnames[3:3] = ["designation", "tier"]
            fieldnames += ["composite_score", "percentile"]

        try:
            with resolved.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for i, r in enumerate(data.ranked_contributors):
                    row = {
                        "rank": i + 1,
                        "name": _neutralise_csv_cell(r.stats.name),
                        "email": _neutralise_csv_cell(r.stats.email),
                        "commits": r.stats.commit_count,
                        "lines_added": r.stats.lines_added,
                        "lines_deleted": r.stats.lines_deleted,
                        "net_lines": r.stats.net_lines,
                        "active_days": r.stats.active_days,
                        "last_commit_date": r.stats.last_commit_date.isoformat(),
                    }
                    if ranked:
                        row["designation"] = _neutralise_csv_cell(r.tier_designation)
                        row["tier"] = r.tier
                        row["composite_score"] = r.composite_score
                        row["percentile"] = r.percentile
                    writer.writerow(row)
        except OSError as exc:
            raise OutputPathError(f"Failed to write CSV report to '{resolved}': {exc}") from exc

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
            "commit_concentration": _compute_commit_concentration(data.ranked_contributors),
            # Rounded to two places: the third decimal of a Gini over a handful
            # of contributors is noise, and printing it implies a precision the
            # sample does not carry.
            "gini_coefficient": round(
                gini_coefficient([r.stats.commit_count for r in data.ranked_contributors]), 2
            ),
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
    ) -> dict[str, str]:
        """Build all chart JSON specifications for the report.

        Each returned value is a Plotly figure serialised as a JSON string,
        suitable for embedding in an application/json script block and
        rendered client-side via Plotly.newPlot(). Returns the JSON string
        'null' for any chart that lacks sufficient data.

        The heatmap key contains a compact daily-count payload rather than
        a Plotly spec. The client builds the GitHub-style grid from this
        data, navigating between years and contributors via Plotly.react().

        Args:
            data: The complete report dataset.

        Returns:
            A dict mapping chart identifier to JSON string.
        """
        return {
            "timeline": _build_timeline_chart(data.commits),
            "contributor_timeline": _build_contributor_timeline_chart(
                data.commits, data.ranked_contributors
            ),
            "heatmap": _build_heatmap_data(
                data.commits,
                data.ranked_contributors,
                data.metadata.analysis_since,
                data.metadata.analysis_until,
            ),
            "contributor_commits": _build_contributor_commits_chart(data.ranked_contributors),
            "contributor_lines": _build_contributor_lines_chart(data.ranked_contributors),
            "pie_commits": _build_commit_share_pie(data.ranked_contributors),
            "pie_lines": _build_lines_share_pie(data.ranked_contributors),
            "lorenz": _build_lorenz_chart(data.ranked_contributors),
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
            line={"color": _CATEGORICAL_PALETTE[0], "width": 2},
            fillcolor=_translucent(_CATEGORICAL_PALETTE[0], 0.10),
            hovertemplate="Week of %{x}<br>Commits: %{y}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["xaxis"] = {"type": "category", "tickangle": -45, "automargin": True}
    fig.update_layout(
        **layout,
        xaxis_title="Week",
        yaxis_title="Commits",
        height=280,
    )
    return _to_json(fig)


def _build_contributor_timeline_chart(
    commits: list[Commit],
    ranked: list[RankedContributor],
) -> str:
    """Build a per-contributor weekly commit frequency line chart.

    Each contributor is represented as a separate Scatter trace, in ranked
    order, so the highest-composite-score contributor appears first in the
    legend. Commits from contributors absent from the ranked list (filtered by
    min_commits) are excluded.

    At most `_MAX_SERIES` contributors are drawn. Beyond that the palette would
    have to repeat, and two people sharing a colour and a line style makes the
    chart assert something untrue -- a reader has no way to tell which line
    belongs to whom. The per-contributor detail for everyone else remains in
    the rankings table and in the heatmap's contributor filter, both of which
    scale without a colour budget.

    Args:
        commits: All commits in the analysis window.
        ranked: Ranked contributor list in composite score order.

    Returns:
        A Plotly figure JSON string, or 'null' if fewer than two
        contributors are present or no commits fall within the window.
    """
    if not commits or len(ranked) < 2:
        return "null"

    shown = ranked[:_MAX_SERIES]
    weekly_per_email: dict[str, dict[str, int]] = {r.stats.email.lower(): {} for r in shown}

    for commit in commits:
        email = commit.author_email.lower()
        if email not in weekly_per_email:
            continue
        d = commit.timestamp.date()
        week_start = (d - datetime.timedelta(days=d.weekday())).isoformat()
        weekly_per_email[email][week_start] = weekly_per_email[email].get(week_start, 0) + 1

    all_weeks = sorted({week for bins in weekly_per_email.values() for week in bins})
    if not all_weeks:
        return "null"

    fig = go.Figure()
    for i, r in enumerate(shown):
        email = r.stats.email.lower()
        bins = weekly_per_email.get(email, {})
        counts = [bins.get(w, 0) for w in all_weeks]
        fig.add_trace(
            go.Scatter(
                x=all_weeks,
                y=counts,
                mode="lines",
                name=_sanitise_chart_label(r.stats.name),
                line={"color": _CATEGORICAL_PALETTE[i], "width": 2},
                hovertemplate="Week of %{x}<br>Commits: %{y}<extra></extra>",
            )
        )

    layout = _base_layout()
    layout["xaxis"] = {"type": "category", "tickangle": -45, "automargin": True}
    layout["showlegend"] = True
    layout["legend"] = {"orientation": "h", "y": 1.12, "x": 0}
    fig.update_layout(
        **layout,
        xaxis_title="Week",
        yaxis_title="Commits",
        height=320,
    )
    return _to_json(fig)


def _build_heatmap_data(
    commits: list[Commit],
    ranked_contributors: list[RankedContributor],
    analysis_since: datetime.date,
    analysis_until: datetime.date,
) -> str:
    """Build a compact daily commit-count payload for client-side heatmap rendering.

    The payload contains three keys:
    - years: integer list covering analysis_since.year through analysis_until.year
    - contributors: ordered list of {email, name} dicts; "__aggregated__" is always
      first, followed by contributors in ranked order
    - daily_counts: dict keyed by email (including "__aggregated__") mapping
      ISO 8601 date strings to integer commit counts for that calendar day

    The client builds the GitHub-style grid (7 rows Mon-Sun, calendar-week columns)
    from this data. Year tabs and a contributor dropdown drive Plotly.react() calls
    without re-fetching or recomputing server-side data.

    Args:
        commits: All commits in the analysis window.
        ranked_contributors: Contributor list in rank order, used to determine
            the dropdown ordering and to key per-contributor counts.
        analysis_since: Start of the analysis window.
        analysis_until: End of the analysis window.

    Returns:
        A JSON string safe for embedding in an application/json script block.
        The sentinel sequence "</" is escaped to prevent premature script
        block termination.
    """
    years = list(range(analysis_since.year, analysis_until.year + 1))

    agg_counts: defaultdict[str, int] = defaultdict(int)
    per_email: dict[str, defaultdict[str, int]] = {}

    for commit in commits:
        date_str = commit.timestamp.date().isoformat()
        agg_counts[date_str] += 1
        email_key = commit.author_email.lower()
        if email_key not in per_email:
            per_email[email_key] = defaultdict(int)
        per_email[email_key][date_str] += 1

    contributors: list[dict[str, str]] = [{"email": "__aggregated__", "name": "All Contributors"}]
    daily_counts: dict[str, dict[str, int]] = {"__aggregated__": dict(agg_counts)}

    for r in ranked_contributors:
        email_key = r.stats.email.lower()
        if email_key in per_email:
            contributors.append({"email": email_key, "name": _sanitise_chart_label(r.stats.name)})
            daily_counts[email_key] = dict(per_email[email_key])

    payload: dict[str, object] = {
        "years": years,
        "contributors": contributors,
        "daily_counts": daily_counts,
    }
    return json.dumps(payload).replace("</", "<\\/")


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

    names = [_sanitise_chart_label(r.stats.name) for r in reversed(ranked)]
    counts = [r.stats.commit_count for r in reversed(ranked)]
    tiers = [r.tier_designation for r in reversed(ranked)]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=names,
            orientation="h",
            marker_color=_CATEGORICAL_PALETTE[0],
            customdata=tiers,
            hovertemplate="%{y}<br>Commits: %{x}<br>Tier: %{customdata}<extra></extra>",
            text=[str(c) for c in counts],
            textposition="outside",
        )
    )
    fig.update_layout(
        **_base_layout(),
        xaxis_title="Commits",
        height=max(280, min(len(ranked) * 44 + 80, _MAX_CHART_HEIGHT)),
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

    names = [_sanitise_chart_label(r.stats.name) for r in ranked]
    added = [r.stats.lines_added for r in ranked]
    deleted = [r.stats.lines_deleted for r in ranked]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Lines Added",
            x=names,
            y=added,
            marker_color=_LINES_ADDED_COLOUR,
            hovertemplate="%{x}<br>Added: %{y:,}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Lines Deleted",
            x=names,
            y=deleted,
            marker_color=_LINES_DELETED_COLOUR,
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
        [(_sanitise_chart_label(r.stats.name), r.stats.commit_count) for r in sorted_r]
    )

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            textposition="outside",
            textinfo="label+percent",
            marker={"colors": _pie_colors(len(labels), has_other=labels[-1] == _OTHER_LABEL)},
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
        [(_sanitise_chart_label(r.stats.name), r.stats.lines_changed) for r in sorted_r]
    )

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            textposition="outside",
            textinfo="label+percent",
            marker={"colors": _pie_colors(len(labels), has_other=labels[-1] == _OTHER_LABEL)},
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


def _build_lorenz_chart(ranked: list[RankedContributor]) -> str:
    """Build a Lorenz curve of commit distribution across contributors.

    The diagonal is perfect equality -- every contributor with the same number
    of commits. The plotted curve bows beneath it in proportion to how
    concentrated activity actually is.

    The Gini coefficient summarising that gap is rendered by the template on
    the section heading, not here. As a chart title it was anchored top-left,
    which is where Plotly also anchors the legend, so the two overlapped.

    This is a statement about the repository, not about any person in it. No
    contributor is named, and the curve is unchanged by who is where in it,
    which is why it remains in the default report while the per-person ranking
    does not.

    Args:
        ranked: Contributor list. Only the commit counts are used.

    Returns:
        A Plotly figure JSON string, or 'null' if there are fewer than two
        contributors -- a Lorenz curve over one person is the diagonal, which
        conveys nothing.
    """
    if len(ranked) < 2:
        return "null"

    counts = [r.stats.commit_count for r in ranked]
    curve = lorenz_curve(counts)

    xs = [round(x * 100, 4) for x, _ in curve]
    ys = [round(y * 100, 4) for _, y in curve]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[0, 100],
            y=[0, 100],
            mode="lines",
            name="Perfect equality",
            line={"color": _EQUALITY_LINE_COLOUR, "width": 2, "dash": "dot"},
            hovertemplate="Perfect equality<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            name="Observed distribution",
            line={"color": _CATEGORICAL_PALETTE[0], "width": 2},
            fill="tonexty",
            fillcolor=_translucent(_CATEGORICAL_PALETTE[0], 0.12),
            hovertemplate=(
                "Least active %{x:.0f}% of contributors<br>made %{y:.0f}% of commits<extra></extra>"
            ),
        )
    )

    layout = _base_layout()
    layout["showlegend"] = True
    layout["legend"] = {"orientation": "h", "y": 1.14, "x": 0}
    fig.update_layout(
        **layout,
        xaxis_title="Share of contributors (%)",
        yaxis_title="Share of commits (%)",
        height=320,
    )
    return _to_json(fig)


def _compute_commit_concentration(ranked: list[RankedContributor]) -> int:
    """Count the contributors who between them authored half the commits.

    The minimum number of contributors whose combined commit volume
    accounts for at least 50 percent of total commits. A lower value
    indicates a more concentrated history.

    This is deliberately not called a bus factor. Bus factor is a measure
    of knowledge concentration — how much of the surviving code only one
    person understands — which is a property of line ownership, obtained
    from `git blame`, not of commit counts. Commit volume is a weak proxy
    for it: a contributor with many small commits outranks one who wrote
    a subsystem in a handful of large ones. The honest name is the one
    that describes what is actually measured.

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


# Characters that make a spreadsheet treat a cell as a formula rather than text.
# Tab and carriage return are included because a leading one is skipped by the
# parser, exposing whatever follows it.
_CSV_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


def _assert_not_symlink(output_path: Path) -> None:
    """Refuse to write a report through a symbolic link.

    `Path.write_text` follows a symlink, so an output path pointing at one
    overwrites whatever it targets. Combined with an output path taken from an
    auto-discovered configuration file, that is a way for a repository to
    choose which of the victim's files a 4 MB report lands on.

    The check must run on the path **as given**. `Path.resolve()` follows
    symlinks, so a resolved path is already the target and reports
    `is_symlink() is False` -- checking after resolution silently passes every
    time, which is exactly how the first version of this guard failed.

    Args:
        output_path: The output path as supplied, before resolution.

    Raises:
        OutputPathError: If the path is a symbolic link.
    """
    if output_path.is_symlink():
        raise OutputPathError(
            f"Refusing to write through the symbolic link '{output_path}'. "
            "Writing would overwrite the link's target rather than the link. "
            "Choose a regular file path, or remove the link first."
        )


def _neutralise_csv_cell(value: str) -> str:
    """Prevent a text cell from being executed as a spreadsheet formula.

    Author names and addresses come from commit metadata, which anybody who has
    ever contributed to the analysed repository controls. Excel and LibreOffice
    evaluate a cell beginning with `=`, `+`, `-` or `@` as a formula, which is a
    route to `HYPERLINK` exfiltration and, historically, DDE command execution.
    Reveille writes the CSV with a BOM specifically so Excel opens it directly,
    which makes this the likely path rather than an unlikely one.

    The mitigation is the conventional one: a leading apostrophe, which every
    major spreadsheet reads as "treat the rest as text" and does not display.

    Only free-text columns are passed through here. Numeric columns are written
    from integers and floats, so a leading `-` there is a real minus sign.

    Args:
        value: A free-text cell value derived from repository metadata.

    Returns:
        The value, prefixed with an apostrophe if it would otherwise be
        interpreted as a formula.
    """
    if value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def _sanitise_chart_label(value: str) -> str:
    """Strip HTML tags, null bytes, and surrounding whitespace from a chart label.

    Contributor names are sourced from Git commit metadata and must not carry
    HTML tags into Plotly trace fields. _to_json escapes </script> sequences,
    but raw HTML tags in label text can produce unexpected browser rendering.
    This function removes them before trace construction.

    Preserves all characters legitimate in contributor names: letters, digits,
    spaces, hyphens, apostrophes, periods, ampersands, and parentheses.

    Args:
        value: The raw string to sanitise.

    Returns:
        The sanitised string with HTML tags stripped, null bytes removed,
        and surrounding whitespace trimmed.
    """
    value = _SCRIPT_BLOCK_RE.sub("", value)
    value = _HTML_TAG_RE.sub("", value)
    value = value.replace("\x00", "")
    return value.strip()


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
    labels = [i[0] for i in top] + [_OTHER_LABEL]
    values = [i[1] for i in top] + [others_total]
    return labels, values


def _pie_colors(n: int, has_other: bool = False) -> list[str]:
    """Return n slice colours, assigned in fixed palette order.

    Args:
        n: Number of colours required.
        has_other: Whether the final slice is the aggregated "Other
            Contributors" residual rather than a named contributor.

    Returns:
        A list of n hex colour strings. No colour is ever repeated within a
        single chart: identity slices take the categorical palette in order,
        and the residual slice takes a reserved neutral.
    """
    if has_other and n >= 1:
        return [_CATEGORICAL_PALETTE[i] for i in range(n - 1)] + [_OTHER_SLICE_COLOUR]
    return [_CATEGORICAL_PALETTE[i] for i in range(n)]


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
        # Plotly measures the rendered tick labels and axis title and grows
        # the margin to fit them. Without it the fixed bottom margin of 50px
        # is a guess: it was too small for -45 degree date labels, so the
        # "Week" title was drawn on top of them, and too small on the left
        # for a contributor axis, which truncated names to "dabot[bot]".
        "xaxis": {"automargin": True},
        "yaxis": {"automargin": True},
        "showlegend": False,
        "modebar": {"remove": ["logo"]},
    }


def _to_json(fig: go.Figure) -> str:
    r"""Serialise a Plotly figure to a JSON specification string.

    Every theme-dependent colour is stripped from the layout before
    serialisation, because a chart specification is rendered under both
    themes and a colour baked in here can only be right under one of them.
    The client-side theme manager is the single source of these values.

    This runs at the one point every chart passes through, so a builder
    that sets an axis colour cannot leak it into the document. Before
    this, two builders and the shared base layout each set the light
    theme's grid and line colours; under the dark theme they rendered a
    14:1 grid over the plot area, because the manager's attempt to
    override them never took effect.

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

    # Plotly.py serialises its entire default template into every figure:
    # 7,105 bytes per chart, 84% of each specification, and the same bytes
    # each time. Plotly.js registers the same default client-side, so the
    # copy carried in the document changes nothing about how a chart draws.
    # What it does carry is a light-theme palette -- a plot background, a
    # white grid, an axis colour -- inside a document rendered under two
    # themes, which is the class of defect this module has just been
    # cleared of. Every colour a chart actually depends on is set
    # explicitly, by the builder for the data and by the theme manager for
    # the surface.
    layout.pop("template", None)

    _strip_theme_colours(layout)
    raw["layout"] = layout
    return json.dumps(raw).replace("</", "<\\/")


#: Layout keys whose value is a colour that differs between the two themes.
#: Each entry is a path of nested layout keys. `_strip_theme_colours`
#: removes every one of these, and a fitness function asserts that no
#: emitted chart specification contains any of them.
_THEME_COLOUR_PATHS: tuple[tuple[str, ...], ...] = (
    ("paper_bgcolor",),
    ("plot_bgcolor",),
    ("font", "color"),
    ("legend", "bgcolor"),
    ("legend", "bordercolor"),
    ("legend", "font", "color"),
    ("hoverlabel", "bgcolor"),
    ("hoverlabel", "bordercolor"),
    ("hoverlabel", "font", "color"),
    ("modebar", "bgcolor"),
    ("modebar", "color"),
    ("modebar", "activecolor"),
)

#: Axis-local colour keys, stripped from every axis the layout declares.
#: Plotly numbers additional axes `xaxis2`, `yaxis3` and so on, so the
#: axis names are matched by prefix rather than listed.
_AXIS_COLOUR_KEYS: tuple[str, ...] = (
    "gridcolor",
    "linecolor",
    "zerolinecolor",
    "tickcolor",
)


def _strip_theme_colours(layout: dict[str, Any]) -> None:
    """Remove every theme-dependent colour from a Plotly layout, in place.

    Args:
        layout: The layout mapping of a serialised Plotly figure.
    """
    for path in _THEME_COLOUR_PATHS:
        node: Any = layout
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(path[-1], None)

    for name, value in layout.items():
        if not name.startswith(("xaxis", "yaxis")) or not isinstance(value, dict):
            continue
        for key in _AXIS_COLOUR_KEYS:
            value.pop(key, None)
