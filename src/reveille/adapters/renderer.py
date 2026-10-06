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
that time. On theme toggle every chart is re-plotted through that same
path, deliberately not through Plotly.relayout(); the template records
why, and the short version is one path, one set of semantics.

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
import itertools
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import plotly.offline
from jinja2 import (
    Environment,
    PackageLoader,
    StrictUndefined,
    TemplateNotFound,
    TemplatesNotFound,
    select_autoescape,
)

from reveille.domain.concentration import gini_coefficient, lorenz_curve
from reveille.domain.files import extension_breakdown, hotspots
from reveille.domain.models import (
    Commit,
    ContributorStats,
    FileStats,
    RankedContributor,
    ReportData,
)
from reveille.domain.profile import repository_profile
from reveille.domain.summary import longest_quiet_run, summarise
from reveille.exceptions import OutputPathError, RenderError

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
# Four slots, and four is not a style choice -- it is the measured ceiling.
#
# A series colour here has to satisfy three constraints at once, because one
# fixed set is drawn on both themes:
#
#   * >= 3:1 against BOTH plot surfaces (#f6f8fa light, #161b22 dark), since
#     the theme toggle changes the surface and not the series;
#   * >= 15 OKLab dE from every other slot in normal vision, below which two
#     series are indistinguishable to everyone;
#   * >= 6 OKLab dE from every other slot under simulated protanopia,
#     deuteranopia and tritanopia (Vienot-Brettel-Mollon), the documented
#     floor that is admissible only alongside secondary encoding.
#
# Searched over a pool of 29 candidates, the largest set satisfying all three
# is four. The previous eight-slot palette failed 13 of its 28 pairs, and not
# only for colour-blind readers: orange against red measured 7.1 in NORMAL
# vision, magenta against red 7.8, blue against violet 9.8. Three pairs of
# series that nobody could tell apart.
#
# Hues are Okabe & Ito's Color Universal Design set (2008) where they clear
# the dual-surface contrast requirement; their sky blue, yellow and pink do
# not, and are excluded rather than fixed, since darkening them collapses the
# separation that made them worth having.
#
# Secondary encoding is present and load-bearing: every chart using these has
# a legend, the pies carry direct labels, and the contributor table restates
# every figure as text. Beyond four series the honest move is to aggregate,
# not to invent a fifth colour -- `_MAX_SERIES` and `_PIE_MAX_SLICES` both do.
# `tests/unit/adapters/test_palette.py` recomputes all three constraints, so
# a future edit that breaks one fails the build rather than the reader.
_CATEGORICAL_PALETTE: list[str] = [
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # bluish green
    "#8E5572",  # muted plum
]

# Series colours are assigned in fixed order and never cycled. A ninth
# contributor does not get slot one again -- two people sharing a colour makes
# the chart state something false. Charts that could exceed the palette cap
# their series count instead; see _build_contributor_timeline_chart.
_MAX_SERIES: int = len(_CATEGORICAL_PALETTE)

#: Dash patterns paired with the palette, in the same fixed order. Colour
#: alone cannot carry identity: a reader with a colour vision deficiency,
#: a greyscale print and a photocopied page all lose it, and a legend is
#: a key to the colour rather than a substitute for it.
_LINE_DASHES: tuple[str, ...] = ("solid", "dash", "dot", "dashdot")

# Maximum individual slices in a pie chart. A slice is an identity, so it
# needs a distinguishable colour; beyond the palette, contributors aggregate
# into a single "Other Contributors" slice rather than reusing a hue. Derived
# from the palette so the two cannot drift: a pie once drew a ninth slice in
# slot one, sharing a colour with the top contributor in the one chart where
# every slice is visible at once.
_PIE_MAX_SLICES: int = len(_CATEGORICAL_PALETTE)

# Added and deleted lines are a semantic pair, not two arbitrary categories, so
# they are named rather than taken from the categorical order. They are not in
# the categorical palette. Each is held to the same contrast floor as the
# palette, and the pair stays 9.5 OKLab units apart under simulated
# protanopia, above the floor of 6 -- asserted in test_palette.py.
_LINES_ADDED_COLOUR: str = "#008300"
_LINES_DELETED_COLOUR: str = "#e66767"

# The trailing "Other Contributors" slice is a residual, not an identity, so it
# gets a neutral rather than a hue from the categorical order. Without this the
# ninth slice wrapped around to slot one and shared a colour with the
# top-ranked contributor inside the same pie -- two different things drawn the
# same way, in the one chart where every slice is visible at once.
# A true neutral: 4.27:1 on the light plot surface, 3.81:1 on the dark one,
# and zero chroma, which is what makes it read as an aggregate rather than a
# fifth person. Asserted in tests/unit/adapters/test_palette.py.
_OTHER_SLICE_COLOUR: str = "#767676"


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
_EQUALITY_LINE_COLOUR: str = "#767676"

# Pre-compiled patterns for sanitising user-controlled strings.
# _SCRIPT_BLOCK_RE removes script elements including their content before
# _HTML_TAG_RE strips remaining tags, preventing script body text from
# surviving as raw output after tag removal.
_SCRIPT_BLOCK_RE: re.Pattern[str] = re.compile(
    r"<script\b[^>]*>.*?</script\b[^>]*>", re.IGNORECASE | re.DOTALL
)
_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")

# Module-level cache for the Plotly JS bundle.
# plotly.offline.get_plotlyjs() reads ~4.8 MB of minified JavaScript from
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
                undefined=StrictUndefined,
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
                # The profile is rendered from these by the template, in HTML
                # and CSS. It was a Plotly radar until 0.9.0; see ADR 0012.
                profile=repository_profile(
                    data.commits,
                    data.file_stats,
                    data.metadata.analysis_since,
                    data.metadata.analysis_until,
                ),
                chart_tables={
                    name: _accessible_table(name, specification)
                    for name, specification in charts.items()
                },
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

        The payload contains repository metadata, contributor statistics, and
        the derived summary measures; the scoring fields are present only when
        ranking is enabled. The raw commits list is excluded. Dates are ISO
        8601 strings. Suitable for consumption by dashboards, data warehouses,
        and scripts without parsing HTML.

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
                # Commits dated after the end of a default window: counted in
                # no figure, and stated here so the omission is not silent.
                "commits_dated_after_window": data.provenance.commits_dated_after_window,
                "shallow_clone": data.provenance.shallow_clone,
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
                # Added at schema 1.1. Without these, a consumer seeing
                # `min_commits` in the filters cannot tell what population the
                # figures above describe, and the rows will not sum to
                # `total_commits`. Both are stated rather than left to
                # arithmetic.
                "population_size": derived["population_size"],
                "contributors_below_threshold": derived["contributors_below_threshold"],
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
        # `min_commits` filters the listing, not the analysis, so every figure
        # here is computed over the whole repository. See ADR 0011.
        population = [stats.commit_count for stats in _population(data)]
        return {
            "commit_concentration": _compute_commit_concentration(population),
            # Rounded to two places: the third decimal of a Gini over a handful
            # of contributors is noise, and printing it implies a precision the
            # sample does not carry.
            "gini_coefficient": round(gini_coefficient(population), 2),
            # Gini's maximum for a sample of n is (n-1)/n, so a report over
            # two contributors can never exceed 0.50 however lopsided the
            # split. Showing 0.23 against a stated 0-to-1 scale invites the
            # reader to conclude "23% of the way to maximum concentration"
            # when it is 46% of the achievable range.
            "gini_ceiling": _ceiling_text(len(population)),
            # The population the figures above describe, which is not the
            # number of rows in the table when `min_commits` is in use. The
            # template states it beside the Gini so the reader is never left
            # to infer it from a row count.
            "population_size": len(population),
            "contributors_below_threshold": len(data.suppressed_contributors),
            "longest_inactive_streak": longest_quiet_run(data.commits),
            # A text alternative for the heatmap. Its payload is a daily
            # grid rather than a Plotly figure, so `_accessible_table` has
            # nothing to read, and a day-by-day table would run to
            # hundreds of rows per contributor. These are the figures a
            # reader takes from the picture: how much, over how many days,
            # and where the peak is.
            "heatmap_summary": _summarise_activity(data.commits),
            # Written findings, generated from these same numbers by rules.
            # See domain/summary.py: no model, no network, and the same
            # history always produces the same sentences.
            # Measured against the end of the window, so a repository that
            # has gone quiet says so. Without it the dormancy finding was
            # measured against the last commit and could never appear.
            "findings": summarise(
                data.commits, _population(data), today=data.metadata.analysis_until
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
        window = (data.metadata.analysis_since, data.metadata.analysis_until)
        return {
            "timeline": _build_timeline_chart(data.commits, window),
            "contributor_timeline": _build_contributor_timeline_chart(
                data.commits, data.ranked_contributors, window
            ),
            "heatmap": _build_heatmap_data(
                data.commits,
                data.ranked_contributors,
                data.metadata.analysis_since,
                data.metadata.analysis_until,
            ),
            "contributor_lines": _build_contributor_lines_chart(data.ranked_contributors),
            "pie_commits": _build_commit_share_pie(
                data.ranked_contributors,
                sum(s.commit_count for s in data.suppressed_contributors),
            ),
            "lorenz": _build_lorenz_chart([stats.commit_count for stats in _population(data)]),
            "commit_size": _build_commit_size_chart(data.commits),
            "hotspots": _build_hotspot_chart(data.file_stats),
            "extensions": _build_extension_chart(data.file_stats),
        }


# ------------------------------------------------------------------
# Chart construction functions
# ------------------------------------------------------------------


def _ceiling_text(population: int) -> str:
    """Format the largest Gini a population of this size can reach.

    The maximum is (n-1)/n. Rounded to two places it reads "1.00" from 200
    contributors upward, beside a sentence saying the maximum is not 1, so
    the figure is truncated, not rounded, to three places when two would
    reach 1.

    Args:
        population: The number of contributors the Gini describes.

    Returns:
        The ceiling as text, or "0.00" for fewer than two contributors.
    """
    if population < 2:
        return "0.00"
    ceiling = (population - 1) / population
    if round(ceiling, 2) < 1:
        return f"{ceiling:.2f}"
    return f"{math.floor(ceiling * 1000) / 1000:.3f}"


def _population(data: ReportData) -> list[ContributorStats]:
    """Every contributor in the repository, listed or not.

    ADR 0011: `min_commits` chooses who is *listed*; every figure describes the
    whole repository. The Gini honoured that and the Lorenz curve and the
    profile did not, because each caller assembled the population for itself
    and two of the three assembled it wrongly. Under `--min-commits 100` this
    repository printed a Gini of 0.25 over two contributors, a Lorenz
    specification of `null`, and a profile axis of 0.0 described as "one
    contributor, so there is nothing to spread" -- three statements about one
    population, in one document, disagreeing with each other.

    One definition, used by everything that describes the repository, so they
    cannot diverge again. Per-contributor charts deliberately do not use it: a
    chart that names people must show only the people who are listed.

    Args:
        data: The complete report dataset.

    Returns:
        Listed contributors followed by those held back by `min_commits`.
    """
    return [ranked.stats for ranked in data.ranked_contributors] + list(
        data.suppressed_contributors
    )


def _contributor_labels(ranked: list[RankedContributor]) -> dict[str, str]:
    """Map each contributor's email to a label unique within the report.

    ADR 0002 makes the lowercased email the identity key. The display
    name is not unique -- two people can share one, and so can one person
    committing under two addresses before a `.mailmap` ties them
    together. Charts keyed on the name inherit that ambiguity, and Plotly
    resolves a repeated category label differently depending on the trace
    type: a bar chart collapses the bars onto one category, a pie sums
    the slices, and a line chart draws two legend entries a reader cannot
    tell apart.

    Measured against this repository before its `.mailmap` existed, with
    201 commits under one address and 1 under another:

        contributors table   201 and 1, listed separately
        commits bar chart    201, the second bar drawn over the first
        commit share pie     202, the two labels silently summed

    Three views of one repository, three answers. A name that occurs once
    is used as it is; a name that occurs more than once carries the
    address that distinguishes it, and only then -- disambiguating every
    label would clutter the common case for no reader benefit.

    Args:
        ranked: Every contributor in the report.

    Returns:
        A mapping from lowercased email to the label to draw.
    """
    sanitised = {r.stats.email.lower(): _sanitise_chart_label(r.stats.name) for r in ranked}
    occurrences: dict[str, int] = defaultdict(int)
    for label in sanitised.values():
        occurrences[label] += 1

    return {
        email: (label if occurrences[label] == 1 else f"{label} <{_sanitise_chart_label(email)}>")
        for email, label in sanitised.items()
    }


#: Axis pairs to read a table from, per Plotly trace type. A chart is
#: drawn from arrays, so its text alternative can be read back out of the
#: same arrays rather than assembled a second time and left to drift.
_TABLE_AXES: dict[str, tuple[str, str]] = {
    "bar": ("x", "y"),
    "scatter": ("x", "y"),
    "pie": ("labels", "values"),
}

#: Column headings for each chart's tabular equivalent. Stated rather
#: than derived: a polar plot and a pie have no axis titles to read, and
#: a horizontal bar's titles are the wrong way round. The first entry
#: names the category column; where a chart has several series, their
#: names supply the remaining columns.
_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "timeline": ("Week", "Commits"),
    "contributor_timeline": ("Week",),
    "lorenz": ("Share of contributors (%)",),
    "commit_size": ("Lines changed in one commit", "Commits"),
    "hotspots": ("File", "Lines changed"),
    "extensions": ("File type", "Lines changed"),
    "contributor_lines": ("Contributor",),
    "pie_commits": ("Contributor", "Commits"),
}


def _summarise_activity(commits: list[Commit]) -> str:
    """Describe a commit heatmap in one sentence, for assistive technology.

    A heatmap encodes magnitude by colour across a calendar, and its
    payload is a daily grid rather than a figure specification, so there
    is nothing to read a table out of and a day-by-day one would run to
    hundreds of rows. This states what a sighted reader takes from the
    picture instead.

    Args:
        commits: All commits in the analysis window.

    Returns:
        A sentence, or a statement that there is nothing to describe.
    """
    if not commits:
        return "No commits fall within the analysis window."

    per_day: dict[datetime.date, int] = defaultdict(int)
    for commit in commits:
        per_day[commit.timestamp.date()] += 1
    busiest, peak = max(per_day.items(), key=lambda item: (item[1], item[0]))
    return (
        f"{len(commits):,} commits across {len(per_day):,} active days, "
        f"between {min(per_day).isoformat()} and {max(per_day).isoformat()}. "
        f"The busiest day was {busiest.isoformat()} with {peak:,}."
    )


def _series_from_spec(specification: str) -> list[tuple[str, list[Any], list[Any]]]:
    """Read each trace's categories and values out of a chart specification.

    Args:
        specification: A chart's Plotly JSON, or the string 'null'.

    Returns:
        One `(series name, categories, values)` triple per usable trace.
    """
    if not specification or specification == "null":
        return []
    try:
        figure = json.loads(specification)
    except json.JSONDecodeError:  # pragma: no cover - _to_json emits valid JSON
        return []

    series: list[tuple[str, list[Any], list[Any]]] = []
    for trace in figure.get("data") or []:
        axes = _TABLE_AXES.get(trace.get("type", "scatter"))
        if axes is None:
            continue
        categories, values = trace.get(axes[0]), trace.get(axes[1])
        # A horizontal bar puts its categories on y.
        if trace.get("orientation") == "h":
            categories, values = values, categories
        if not categories or not values:
            continue
        series.append((str(trace.get("name") or ""), list(categories), list(values)))
    return series


def _accessible_table(chart: str, specification: str) -> dict[str, Any]:
    """Return a tabular equivalent of a chart, for assistive technology.

    `role="img"` makes an SVG's children presentational, so the
    `aria-label` is the *only* alternative a screen-reader user gets. A
    label naming the chart type conveys no data, and WCAG 2.1 SC 1.1.1
    asks for an alternative that serves the equivalent purpose. Seven of
    the report's ten charts had nothing else.

    The rows are read back out of the emitted specification, so the table
    cannot come to describe a chart the report is not drawing.

    Args:
        chart: The chart's id, used to look up its column headings.
        specification: That chart's Plotly JSON.

    Returns:
        A mapping with `columns` and `rows`, or an empty mapping when
        there is nothing to describe.
    """
    series = _series_from_spec(specification)
    headings = _TABLE_COLUMNS.get(chart)
    if not series or headings is None:
        return {}

    if len(series) == 1:
        _name, categories, values = series[0]
        columns = list(headings[:2]) or ["Item", "Value"]
        return {
            "columns": columns,
            "rows": [list(pair) for pair in zip(categories, values, strict=False)],
        }

    ordered: list[Any] = []
    for _name, categories, _values in series:
        ordered.extend(c for c in categories if c not in ordered)
    lookup = [
        (name, dict(zip(categories, values, strict=False))) for name, categories, values in series
    ]
    return {
        "columns": [headings[0], *(name or "Value" for name, _ in lookup)],
        "rows": [
            [category, *(values.get(category, "") for _n, values in lookup)] for category in ordered
        ],
    }


def _commit_span(commits: list[Commit]) -> tuple[datetime.date, datetime.date]:
    """The first and last commit dates, for a chart given no analysis window."""
    dates = [c.timestamp.date() for c in commits]
    return min(dates), max(dates)


def _week_starts(first: datetime.date, last: datetime.date) -> list[str]:
    """Every Monday from the week containing `first` to the week containing `last`.

    A weekly chart built only from weeks that had commits skips the quiet
    ones, and a line drawn straight across a gap reads as steady activity --
    the opposite of what happened. Every week in the window gets a point, and
    a week with no commits is drawn as zero.

    Args:
        first: The first day to cover.
        last: The last day to cover.

    Returns:
        ISO dates of each week's Monday, in order.
    """
    monday = first - datetime.timedelta(days=first.weekday())
    weeks: list[str] = []
    while monday <= last:
        weeks.append(monday.isoformat())
        monday += datetime.timedelta(weeks=1)
    return weeks


def _build_timeline_chart(
    commits: list[Commit],
    window: tuple[datetime.date, datetime.date] | None = None,
) -> str:
    """Build a weekly commit frequency line chart.

    Args:
        commits: All commits in the analysis window.
        window: The analysis window's first and last day. Every week in it is
            drawn, including weeks with no commits. Without it, the span of
            the commits themselves is used.

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

    sorted_weeks = _week_starts(*(window or _commit_span(commits)))
    counts = [weekly.get(w, 0) for w in sorted_weeks]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sorted_weeks,
            y=counts,
            mode="lines",
            fill="tozeroy",
            line={"color": _CATEGORICAL_PALETTE[0], "width": 2},
            fillcolor=_translucent(_CATEGORICAL_PALETTE[0], 0.10),
            hovertemplate="Week of %{x|%Y-%m-%d}<br>Commits: %{y:,}<extra></extra>",
        )
    )
    layout = _base_layout()
    # A date axis spaces its own ticks by month or year. As a category axis
    # every week was a label: hundreds of rotated dates over a long window.
    layout["xaxis"] = {"type": "date", "automargin": True}
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
    window: tuple[datetime.date, datetime.date] | None = None,
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
        window: The analysis window's first and last day, as for
            `_build_timeline_chart`.

    Returns:
        A Plotly figure JSON string, or 'null' if fewer than two
        contributors are present or no commits fall within the window.
    """
    if not commits or len(ranked) < 2:
        return "null"

    shown = ranked[:_MAX_SERIES]
    # Built over the full list, not just the drawn subset: a name is only
    # ambiguous relative to every contributor in the report.
    labels = _contributor_labels(ranked)
    weekly_per_email: dict[str, dict[str, int]] = {r.stats.email.lower(): {} for r in shown}

    for commit in commits:
        email = commit.author_email.lower()
        if email not in weekly_per_email:
            continue
        d = commit.timestamp.date()
        week_start = (d - datetime.timedelta(days=d.weekday())).isoformat()
        weekly_per_email[email][week_start] = weekly_per_email[email].get(week_start, 0) + 1

    if not any(weekly_per_email.values()):
        return "null"
    all_weeks = _week_starts(*(window or _commit_span(commits)))

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
                name=labels[r.stats.email.lower()],
                line={
                    "color": _CATEGORICAL_PALETTE[i],
                    "width": 2,
                    # A legend is a colour key, not a second encoding:
                    # resolving it still needs the colour discrimination it
                    # is meant to substitute for. WCAG 1.4.1 asks for
                    # something other than colour, so each series takes its
                    # own dash as well as its own hue.
                    "dash": _LINE_DASHES[i % len(_LINE_DASHES)],
                },
                hovertemplate="Week of %{x|%Y-%m-%d}<br>Commits: %{y:,}<extra></extra>",
            )
        )

    layout = _base_layout()
    # A date axis spaces its own ticks by month or year. As a category axis
    # every week was a label: hundreds of rotated dates over a long window.
    layout["xaxis"] = {"type": "date", "automargin": True}
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

    labels = _contributor_labels(ranked_contributors)
    contributors: list[dict[str, str]] = [{"email": "__aggregated__", "name": "All Contributors"}]
    daily_counts: dict[str, dict[str, int]] = {"__aggregated__": dict(agg_counts)}

    for r in ranked_contributors:
        email_key = r.stats.email.lower()
        if email_key in per_email:
            contributors.append({"email": email_key, "name": labels[email_key]})
            daily_counts[email_key] = dict(per_email[email_key])

    payload: dict[str, object] = {
        "years": years,
        # The grid draws these bounds rather than the whole calendar year, so
        # days before the window or after it are not drawn as days with no
        # commits.
        "since": analysis_since.isoformat(),
        "until": analysis_until.isoformat(),
        "contributors": contributors,
        "daily_counts": daily_counts,
    }
    return json.dumps(payload).replace("</", "<\\/")


def _build_contributor_lines_chart(ranked: list[RankedContributor]) -> str:
    """Build a grouped bar chart of lines added and deleted per contributor.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.

    Returns:
        A Plotly figure JSON string, or 'null' if ranked is empty.
    """
    if not ranked:
        return "null"

    labels = _contributor_labels(ranked)
    names = [labels[r.stats.email.lower()] for r in ranked]
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


def _build_commit_share_pie(ranked: list[RankedContributor], unlisted_commits: int = 0) -> str:
    """Build a donut chart showing each contributor's share of total commits.

    Contributors beyond _PIE_MAX_SLICES are aggregated into a single
    'Other Contributors' slice to maintain legibility. So are the commits of
    contributors `min_commits` kept out of the table: the slices are shares of
    every commit, as ADR 0011 requires of every figure. Without them a listed
    contributor holding 75% of the listed commits was drawn as holding 75% of
    the repository.

    Args:
        ranked: Ranked contributor list sorted by composite score descending.
        unlisted_commits: Commits by contributors below the listing threshold.

    Returns:
        A Plotly figure JSON string, or 'null' if fewer than two slices would
        be drawn. A single slice carries no comparative information.
    """
    if len(ranked) + (1 if unlisted_commits else 0) < 2 or not ranked:
        return "null"

    display = _contributor_labels(ranked)
    sorted_r = sorted(ranked, key=lambda r: r.stats.commit_count, reverse=True)
    labels, values = _aggregate_pie_data(
        [(display[r.stats.email.lower()], r.stats.commit_count) for r in sorted_r]
    )
    if unlisted_commits:
        if labels[-1] == _OTHER_LABEL:
            values[-1] += unlisted_commits
        else:
            labels.append(_OTHER_LABEL)
            values.append(unlisted_commits)

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


def _build_commit_size_chart(commits: list[Commit]) -> str:
    """Build a histogram of change size per commit, on a log-spaced scale.

    Relative code churn -- lines added plus deleted, per commit -- is the
    measure Nagappan and Ball put on a formal footing in "Use of Relative
    Code Churn Measures to Predict System Defect Density" (ICSE 2005).
    What it shows here is the shape of the working rhythm: whether a
    repository advances in many small steps or a few large ones.

    Buckets are log-spaced because change size is heavily skewed. Linear
    buckets over a range that spans one line to ten thousand put almost
    every commit in the first bar, which states nothing.

    This is a property of the history, not of anyone in it: the commits
    are pooled, and no contributor is separated out.

    Args:
        commits: All commits in the analysis window.

    Returns:
        A Plotly figure JSON string, or 'null' if commits is empty.
    """
    if not commits:
        return "null"

    # The first bin starts at zero: a commit can change no counted line (an
    # empty commit, or binary files only), and it was counted under "1-9".
    edges = [0, 10, 50, 200, 1000, 5000]
    dash = "\u2013"  # en dash, written as an escape so it cannot be mistaken
    labels = [*(f"{low:,}{dash}{high - 1:,}" for low, high in itertools.pairwise(edges)), "5,000+"]
    buckets = [0] * len(labels)
    for commit in commits:
        size = commit.lines_added + commit.lines_deleted
        index = len(edges) - 1
        for position, edge in enumerate(edges):
            if size < edge:
                index = max(position - 1, 0)
                break
        buckets[index] += 1

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=buckets,
            marker_color=_CATEGORICAL_PALETTE[0],
            text=[f"{count:,}" if count else "" for count in buckets],
            textposition="outside",
            hovertemplate="%{x} lines changed<br>Commits: %{y}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["xaxis"] = {"type": "category", "automargin": True}

    # The distribution is heavily skewed and the bins are log-spaced, so
    # the bars alone do not tell a reader where the middle sits -- the
    # tallest bar is not the median when the bins double in width each
    # step. Marking the median bucket gives the shape an anchor, which is
    # what turns a row of bars into a distribution a reader can describe.
    sizes = sorted(commit.lines_added + commit.lines_deleted for commit in commits)
    median = sizes[len(sizes) // 2]
    median_index = len(edges) - 1
    for position, edge in enumerate(edges):
        if median < edge:
            median_index = max(position - 1, 0)
            break
    layout["annotations"] = [
        {
            "x": labels[median_index],
            "y": buckets[median_index],
            "yanchor": "bottom",
            "yshift": 22,
            "text": f"median {median:,} lines",
            "showarrow": False,
            "font": {"size": 11},
        }
    ]

    fig.update_layout(
        **layout,
        xaxis_title="Lines changed in one commit",
        yaxis_title="Commits",
        height=300,
    )
    return _to_json(fig)


def _build_hotspot_chart(files: list[FileStats]) -> str:
    """Build a horizontal bar chart of the paths absorbing the most change.

    The churn axis of hotspot analysis (Tornhill, *Your Code as a Crime
    Scene*, 2013), resting on relative code churn (Nagappan & Ball, ICSE
    2005). Reveille reads history and never file content, so it reports
    churn alone rather than crossing it with complexity -- a file that
    changes often is one to look at, not one that is wrong.

    Args:
        files: Per-path activity for the analysis window.

    Returns:
        A Plotly figure JSON string, or 'null' if there is nothing to show.
    """
    ranked = hotspots(files, limit=12)
    if not ranked:
        return "null"

    paths = [_sanitise_chart_label(f.path) for f in reversed(ranked)]
    churn = [f.lines_changed for f in reversed(ranked)]
    commits = [f.commits for f in reversed(ranked)]

    fig = go.Figure(
        go.Bar(
            x=churn,
            y=paths,
            orientation="h",
            marker_color=_CATEGORICAL_PALETTE[0],
            customdata=commits,
            hovertemplate=(
                "%{y}<br>Lines changed: %{x:,}<br>Commits: %{customdata}<extra></extra>"
            ),
            text=[f"{value:,}" for value in churn],
            textposition="outside",
        )
    )
    fig.update_layout(
        **_base_layout(),
        xaxis_title="Lines changed (added + deleted)",
        height=max(280, min(len(ranked) * 30 + 90, _MAX_CHART_HEIGHT)),
    )
    return _to_json(fig)


def _build_extension_chart(files: list[FileStats]) -> str:
    """Build a bar chart of churn totalled by file extension.

    What kind of work a period contained -- source, tests, documentation,
    configuration -- without naming a file or a person.

    Args:
        files: Per-path activity for the analysis window.

    Returns:
        A Plotly figure JSON string, or 'null' if there is nothing to show.
    """
    breakdown = extension_breakdown(files, limit=8)
    if not breakdown:
        return "null"

    labels = [label for label, _ in breakdown]
    values = [value for _, value in breakdown]

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker_color=_CATEGORICAL_PALETTE[2],
            text=[f"{value:,}" for value in values],
            textposition="outside",
            hovertemplate="%{x}<br>Lines changed: %{y:,}<extra></extra>",
        )
    )
    layout = _base_layout()
    layout["xaxis"] = {"type": "category", "automargin": True}
    fig.update_layout(
        **layout,
        xaxis_title="File type",
        yaxis_title="Lines changed",
        height=280,
    )
    return _to_json(fig)


def _build_lorenz_chart(counts: list[int]) -> str:
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
        counts: Commit count per contributor, in any order. Counts rather
            than ranked contributors, because the population this describes
            includes contributors held back by `min_commits`, who have no
            rank. See `_population`.

    Returns:
        A Plotly figure JSON string, or 'null' if there are fewer than two
        contributors -- a Lorenz curve over one person is the diagonal, which
        conveys nothing.
    """
    if len(counts) < 2:
        return "null"

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


def _compute_commit_concentration(counts: list[int]) -> int:
    """Count the contributors who between them authored half the commits.

    The minimum number of contributors whose combined commit volume
    accounts for at least 50 percent of total commits. A lower value
    indicates a more concentrated history.

    This is deliberately not called a bus factor. Bus factor is a measure
    of knowledge concentration -- how much of the surviving code only one
    person understands -- which is a property of line ownership, obtained
    from `git blame`, not of commit counts. Commit volume is a weak proxy
    for it: a contributor with many small commits outranks one who wrote
    a subsystem in a handful of large ones. The honest name is the one
    that describes what is actually measured.

    Takes commit counts rather than ranked contributors because the
    population it must describe includes contributors held back from the
    listing by `min_commits`, who have no rank.

    Args:
        counts: Commit count per contributor, in any order.

    Returns:
        An integer in the range [1, len(counts)]. Returns 0 when `counts`
        is empty or sums to zero.
    """
    if not counts:
        return 0
    total = sum(counts)
    if total == 0:
        return 0
    threshold = total * 0.5
    cumulative = 0
    # `no branch`/`no cover`: the loop always returns. `counts` is non-empty and
    # `total` is positive, both guarded above, so `cumulative` reaches `total`,
    # which is >= total * 0.5. The tail exists because mypy --strict cannot
    # prove that and requires a return on every path.
    for position, count in enumerate(sorted(counts, reverse=True), start=1):  # pragma: no branch
        cumulative += count
        if cumulative >= threshold:
            return position
    return len(counts)  # pragma: no cover - unreachable, see above


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

    Background colours and font colour are intentionally absent. The
    client-side theme manager supplies them at render time, and on a
    theme toggle re-plots each chart through the same path as the first
    paint. Not Plotly.relayout(): handed a nested object it replaces the
    container it names, so a themed xaxis would take the axis title with
    it, and it does not touch the trace-level colorscale the heatmap
    needs. The template carries the full reasoning.

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
        # Numbers in full, with separators, as every label and sentence in
        # the report writes them. Plotly's default printed "1000" beside a
        # bar labelled "1,594", and switched to "25k" above ten thousand.
        "xaxis": {"automargin": True, "separatethousands": True, "exponentformat": "none"},
        "yaxis": {"automargin": True, "separatethousands": True, "exponentformat": "none"},
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
