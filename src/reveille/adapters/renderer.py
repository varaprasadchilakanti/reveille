# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

r"""Report renderer adapter: HTML, JSON and CSV; the only module importing Jinja2 or Plotly.

The HTML report is one self-contained file making no network requests. Each
chart is a Plotly JSON spec in an application/json block, plotted client-side
with Plotly.newPlot() and re-plotted the same way on theme toggle. The heatmap
is a daily-count payload the client turns into a calendar grid.

"</script>" is escaped as "<\/script>" in all embedded JSON.
"""

from __future__ import annotations

import csv
import datetime
import io
import itertools
import json
import math
import os
import re
import secrets
import stat
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

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

from reveille.domain.areas import AreaStatement, PathAnswer, describe_areas, is_automated
from reveille.domain.brief import QUIET_DAYS, Brief
from reveille.domain.coauthors import commits_with_co_authors
from reveille.domain.concentration import gini_coefficient, lorenz_curve
from reveille.domain.files import extension_breakdown, generated_churn, hotspots
from reveille.domain.models import (
    SCHEMA_VERSION,
    CoAuthor,
    Commit,
    ContributorStats,
    FileStats,
    RankedContributor,
    ReportData,
)
from reveille.domain.profile import ProfileAxis, repository_profile
from reveille.domain.state import QUIET_BRANCH_DAYS, RepositoryState
from reveille.domain.summary import Finding, longest_quiet_run, summarise
from reveille.exceptions import OutputPathError, RenderError

# Label of the aggregated residual slice, referenced where its colour is chosen.
_OTHER_LABEL: str = "Other Contributors"

# Identity colours, one per contributor in fixed order, drawn on both themes.
# Four is the measured ceiling for: >= 3:1 on both plot surfaces, >= 15 OKLab dE
# apart in normal vision, >= 6 under simulated CVD. Asserted in test_palette.py.
_CATEGORICAL_PALETTE: list[str] = [
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # bluish green
    "#8E5572",  # muted plum
]

# Never cycled: two people sharing a colour is a false statement. Charts cap
# their series count instead.
_MAX_SERIES: int = len(_CATEGORICAL_PALETTE)

#: Dash patterns paired with the palette, so identity does not rest on colour alone.
_LINE_DASHES: tuple[str, ...] = ("solid", "dash", "dot", "dashdot")

# Maximum named pie slices; the rest aggregate into "Other Contributors".
# Derived from the palette so the two cannot drift.
_PIE_MAX_SLICES: int = len(_CATEGORICAL_PALETTE)

# Added and deleted lines: a semantic pair outside the categorical palette,
# held to the same floors (asserted in test_palette.py).
_LINES_ADDED_COLOUR: str = "#008300"
_LINES_DELETED_COLOUR: str = "#e66767"

# The residual slice is not an identity, so it is a zero-chroma neutral
# (4.27:1 light, 3.81:1 dark; asserted in test_palette.py).
_OTHER_SLICE_COLOUR: str = "#767676"


def _translucent(hex_colour: str, alpha: float) -> str:
    """Return a `#rrggbb` colour as an `rgba(...)` string at the given alpha.

    Fills derive from the palette so the two cannot drift apart.

    Args:
        hex_colour: A colour in `#rrggbb` form.
        alpha: Opacity between 0.0 and 1.0.

    Returns:
        The equivalent CSS `rgba()` string.
    """
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


# Ceiling on a per-contributor bar chart's height, in pixels; bars compress
# past it rather than grow without bound.
_MAX_CHART_HEIGHT: int = 2400

# The Lorenz reference diagonal: neutral, so it reads as scaffolding, not a series.
_EQUALITY_LINE_COLOUR: str = "#767676"

# Sanitising patterns: script blocks go with their content before other tags.
_SCRIPT_BLOCK_RE: re.Pattern[str] = re.compile(
    r"<script\b[^>]*>.*?</script\b[^>]*>", re.IGNORECASE | re.DOTALL
)
_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")

# The ~4.8 MB Plotly bundle, read once per process rather than per report.
_PLOTLY_JS_BUNDLE: str = plotly.offline.get_plotlyjs()


class Renderer:
    """Renders a ReportData instance into a self-contained HTML file."""

    def __init__(self) -> None:
        """Load the Jinja2 environment and validate the template is present.

        Raises:
            RenderError: If the report template is missing from the package.
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
        html = self.html_text(data)
        try:
            _write_replacing(resolved, html, encoding="utf-8")
        except OSError as exc:
            raise OutputPathError(f"Failed to write report to '{resolved}': {exc}") from exc

        return resolved

    def html_text(self, data: ReportData) -> str:
        """Render the HTML report as text, for a file or for stdout.

        Args:
            data: The complete structured report dataset.

        Returns:
            The self-contained HTML document.

        Raises:
            RenderError: If the Jinja2 template raises an error during rendering.
        """
        try:
            profile = repository_profile(
                data.commits,
                data.file_stats,
                data.metadata.analysis_since,
                data.metadata.analysis_until,
            )
            charts = self._build_charts(data)
            derived = self._compute_derived_stats(data)
            plotly_js = _PLOTLY_JS_BUNDLE
            generated_at = data.metadata.generated_at.strftime("%Y-%m-%d %H:%M UTC")
            html = self._template.render(
                data=data,
                charts=charts,
                # Rendered by the template in HTML, CSS and SVG (ADR 0012, 0016).
                profile=profile,
                flower=_profile_flower(profile),
                chart_tables={
                    name: _accessible_table(name, specification)
                    for name, specification in charts.items()
                },
                derived=derived,
                notice=_NOTICE,
                plotly_js=plotly_js,
                generated_at=generated_at,
            )
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"Template rendering failed: {exc}") from exc
        # Macros leave blank lines before the doctype; strip them.
        return str(html).lstrip()

    def render_json(self, data: ReportData, output_path: Path) -> Path:
        """Serialise the report data to a structured JSON file.

        Scoring fields appear only when ranking is enabled; raw commits are
        excluded; dates are ISO 8601.

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
        text = self.json_text(data)
        try:
            _write_replacing(resolved, text, encoding="utf-8")
        except OSError as exc:
            raise OutputPathError(f"Failed to write JSON report to '{resolved}': {exc}") from exc
        return resolved

    def json_text(self, data: ReportData) -> str:
        """Serialise the report data as JSON text, for a file or for stdout.

        Args:
            data: The complete structured report dataset.

        Returns:
            The JSON document, indented.
        """
        derived = self._compute_derived_stats(data)

        payload: dict[str, Any] = {
            # First, so a consumer can decide whether it can parse the rest.
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
            # The inputs, so two disagreeing reports can be reconciled.
            "provenance": {
                "reveille_version": data.provenance.reveille_version,
                "head_sha": data.provenance.head_sha,
                "deterministic": data.provenance.deterministic,
                "mailmap_applied": data.provenance.mailmap_applied,
                # Counted in no figure; stated so the omission is not silent.
                "commits_dated_after_window": data.provenance.commits_dated_after_window,
                "commits_unreadable": data.provenance.commits_unreadable,
                "shallow_clone": data.provenance.shallow_clone,
                "replace_refs_not_followed": data.provenance.replace_refs_not_followed,
                "graft_file_not_followed": data.provenance.graft_file_not_followed,
                "limit": data.provenance.limit,
                "areas": {
                    "enabled": data.provenance.area_authors_enabled,
                    "depth": data.provenance.area_depth,
                },
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
                    # Omitted, not zeroed, when ranking is off: an absent key
                    # cannot be misread as data.
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
                    "co_authored_commits": r.stats.co_authored_commits,
                }
                for i, r in enumerate(data.ranked_contributors[: data.provenance.limit])
            ],
            # The full count, so a bounded list is never read as the whole (ADR 0015).
            "contributors_total": len(data.ranked_contributors),
            "contributors_truncated": _truncated(data.ranked_contributors, data.provenance.limit),
            "derived": {
                "commit_concentration": derived["commit_concentration"],
                "gini_coefficient": derived["gini_coefficient"],
                "longest_inactive_streak": derived["longest_inactive_streak"],
                # Schema 1.1: states the population the figures describe.
                "population_size": derived["population_size"],
                # Schema 1.1 (ADR 0017): the Gini and concentration describe these people.
                "people": derived["people"],
                "automated_accounts": derived["automated_accounts"],
                "automated_commits": derived["automated_commits"],
                "contributors_below_threshold": derived["contributors_below_threshold"],
                "commits_with_co_authors": commits_with_co_authors(data.commits),
            },
            # Identities credited only by Co-authored-by trailers (ADR 0014).
            # Alphabetical, never by count; a trailer is not verified.
            "co_authors_only": [
                {
                    "name": c.name,
                    "email": c.email,
                    "co_authored_commits": c.co_authored_commits,
                    "automated": is_automated(c.name, c.email),
                }
                for c in _listed_co_authors(data)[: data.provenance.limit]
            ],
            "co_authors_only_total": len(_listed_co_authors(data)),
            "co_authors_only_truncated": _truncated(
                _listed_co_authors(data), data.provenance.limit
            ),
            # ADR 0011 applied to co-authors, as in the HTML: counted, not named.
            "co_authors_only_below_threshold": len(data.co_authors_only)
            - len(_listed_co_authors(data)),
            "notice": _NOTICE,
        }
        if data.provenance.area_authors_enabled:
            # As the HTML section: no per-person count, which would read as a
            # share of an area (ADR 0013).
            payload["areas"] = [
                {
                    "area": a.area,
                    "commits": a.commits,
                    "authors": a.author_count,
                    "automated_accounts": a.automated_count,
                    "not_listed": a.not_listed,
                    "last_changed": a.last_changed.isoformat(),
                    "listed_authors": [
                        {"name": n, "email": e} for n, e in a.named[: data.provenance.limit]
                    ],
                    "listed_authors_truncated": _truncated(a.named, data.provenance.limit),
                    "listed_automated_accounts": [
                        {"name": n, "email": e}
                        for n, e in a.automated_named[: data.provenance.limit]
                    ],
                    "listed_automated_accounts_truncated": _truncated(
                        a.automated_named, data.provenance.limit
                    ),
                }
                for a in _area_statements(data)
            ]

        return json.dumps(payload, indent=2)

    def summary_document(self, data: ReportData) -> dict[str, Any]:
        """Describe the repository in about 2 KB, naming no contributor.

        The default answer for an assistant (ADR 0015): window, totals, measures,
        findings and provenance, with no name or address.

        Args:
            data: The report dataset; line counts are not needed.

        Returns:
            A JSON-serialisable document.
        """
        derived = self._compute_derived_stats(data)
        last = max(c.timestamp.date() for c in data.commits)
        findings = cast(list[Finding], derived["findings"])
        return {
            "schema_version": data.provenance.schema_version,
            "document": "summary",
            "repository": {
                "name": data.metadata.name,
                "analysed_branch": data.metadata.analysed_branch,
                "head_sha": data.provenance.head_sha,
                "analysis_since": data.metadata.analysis_since.isoformat(),
                "analysis_until": data.metadata.analysis_until.isoformat(),
                "shallow_clone": data.provenance.shallow_clone,
                "commits_dated_after_window": data.provenance.commits_dated_after_window,
                "commits_unreadable": data.provenance.commits_unreadable,
                "replace_refs_not_followed": data.provenance.replace_refs_not_followed,
                "graft_file_not_followed": data.provenance.graft_file_not_followed,
            },
            "totals": {
                "commits": data.metadata.total_commits,
                "authors": derived["people"],
                "automated_accounts": derived["automated_accounts"],
                "commits_with_co_authors": commits_with_co_authors(data.commits),
            },
            "measures": {
                "gini_coefficient": derived["gini_coefficient"],
                "commit_concentration": derived["commit_concentration"],
                "longest_quiet_run_days": derived["longest_inactive_streak"],
                "days_since_last_commit": (data.metadata.analysis_until - last).days,
            },
            "findings": [
                {"headline": f.headline, "detail": f.detail, "evidence": f.evidence}
                for f in findings
            ],
            "notice": _NOTICE,
        }

    def summary_text(self, data: ReportData, output_format: str) -> str:
        """Render the summary as JSON or as plain lines.

        Args:
            data: The report dataset.
            output_format: "json" or "text".

        Returns:
            The summary.
        """
        document = self.summary_document(data)
        if output_format == "json":
            return json.dumps(document, indent=2)
        if output_format == "markdown":
            return _summary_markdown(document)
        repo = document["repository"]
        totals = document["totals"]
        measures = document["measures"]
        lines = [
            f"{repo['name']} ({repo['analysed_branch']}), "
            f"{repo['analysis_since']} to {repo['analysis_until']}",
            f"{_counted(totals['commits'], 'commit')} by {_counted(totals['authors'], 'author')}"
            + (
                f" and {_counted(totals['automated_accounts'], 'automated account')}"
                if totals["automated_accounts"]
                else ""
            )
            + "; "
            f"Gini {measures['gini_coefficient']:.2f}, "
            f"longest quiet run {_counted(measures['longest_quiet_run_days'], 'day')}.",
            *(f"- {f['headline']}" for f in document["findings"]),
            document["notice"],
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def who_changed_text(
        answer: PathAnswer,
        window: tuple[datetime.date, datetime.date],
        output_format: str,
        limit: int,
    ) -> str:
        """Render who changed a path, as JSON or plain lines (ADR 0015).

        Every list of people is bounded by `limit` and carries its full total.

        Args:
            answer: The facts for the path.
            window: The analysis window.
            output_format: "json" or "text".
            limit: The most names any list carries.

        Returns:
            The answer.
        """

        def bounded(people: tuple[tuple[str, str], ...]) -> dict[str, Any]:
            return {
                "total": len(people),
                "truncated": len(people) > limit,
                "list": [{"name": n, "email": e} for n, e in people[:limit]],
            }

        if output_format == "json":
            return json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "document": "who-changed",
                    "path": answer.path,
                    "analysis_since": window[0].isoformat(),
                    "analysis_until": window[1].isoformat(),
                    "commits": answer.commits,
                    "last_changed": answer.last_changed.isoformat(),
                    "recently_active": [{"name": n, "email": e} for n, e in answer.recently_active],
                    "authors": bounded(answer.authors),
                    "automated_accounts": bounded(answer.automated),
                    "co_authored_commits": answer.co_authored_commits,
                    "co_authors": bounded(answer.co_authors),
                    "notice": _NOTICE,
                },
                indent=2,
            )

        def names(people: tuple[tuple[str, str], ...]) -> str:
            # A repeated name carries its address.
            repeated = {n for n in (p[0] for p in people) if [p[0] for p in people].count(n) > 1}
            shown = ", ".join(f"{n} <{e}>" if n in repeated else n for n, e in people[:limit])
            rest = len(people) - min(len(people), limit)
            return f"{shown} and {rest:,} more" if rest else shown

        commits = f"{answer.commits:,} commit{'' if answer.commits == 1 else 's'}"
        authors = f"{len(answer.authors):,} author{'' if len(answer.authors) == 1 else 's'}"
        # The window ends where the analysis does, not at the last change.
        lines = [
            f"{answer.path}: {commits} by {authors}, "
            f"from {window[0].isoformat()} to {answer.last_changed.isoformat()}, "
            f"in a window ending {window[1].isoformat()}.",
        ]
        if answer.recently_active:
            lines.append(f"Changed it most recently: {names(answer.recently_active)}.")
        if answer.authors:
            lines.append(f"Authors: {names(answer.authors)}.")
        if answer.automated:
            lines.append(f"Automated: {names(answer.automated)}.")
        if answer.co_authors:
            lines.append(f"Credited as co-author: {names(answer.co_authors)}.")
        lines.append(
            "Who changed it, not who knows or owns it: review and pairing do not "
            "appear in commit history."
        )
        lines.append(_NOTICE)
        return "\n".join(lines) + "\n"

    @staticmethod
    def brief_text(
        facts: Brief,
        *,
        repository: tuple[str, str],
        point: tuple[str, str | None],
        tip: str,
        tags: list[str],
        output_format: str,
        limit: int,
    ) -> str:
        """Render a brief as JSON or plain lines (ADR 0022). Names nobody.

        Args:
            facts: The counts.
            repository: Its name and the analysed branch.
            point: What the caller named, and the commit it resolved to (None for a date).
            tip: The analysed commit, which the next brief can start from.
            tags: Tags whose commit lies in the range, newest first.
            output_format: "json", "text", "markdown" or "line".
            limit: The most entries any list carries.

        Returns:
            The brief.
        """

        def bounded(items: list[Any]) -> dict[str, Any]:
            return {"total": len(items), "truncated": len(items) > limit, "list": items[:limit]}

        named, commit = point
        if output_format == "json":
            return json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "document": "brief",
                    "repository": {"name": repository[0], "analysed_branch": repository[1]},
                    "point": {"from": named, "commit": commit}
                    if commit is not None
                    else {"since": named},
                    "analysed_commit": tip,
                    "first_commit_date": facts.first.isoformat(),
                    "last_commit_date": facts.last.isoformat(),
                    "totals": {
                        "commits": facts.commits,
                        "people": facts.people,
                        "automated_accounts": facts.automated,
                        "commits_with_co_authors": facts.co_authored,
                        "files_added": facts.files_added,
                    },
                    "areas": bounded([{"area": a, "commits": n} for a, n in facts.areas]),
                    "file_types": bounded(
                        [{"type": t, "file_changes": n} for t, n in facts.file_types]
                    ),
                    "active_again_after_quiet_days": QUIET_DAYS,
                    "active_again": bounded(list(facts.active_again)),
                    "tags": bounded(tags),
                    "notice": _NOTICE,
                },
                indent=2,
            )

        if output_format == "markdown":
            return _brief_markdown(facts, repository, point, tip, tags, limit)
        if output_format == "line":
            return _brief_line(facts, repository, named, tip, tags)

        def listed(items: list[str]) -> str:
            rest = len(items) - limit
            shown = ", ".join(items[:limit])
            return f"{shown} and {rest:,} more" if rest > 0 else shown

        since = f"{named} ({commit[:7]})" if commit is not None else named
        who = "1 person" if facts.people == 1 else f"{facts.people:,} people"
        if facts.automated:
            who += f" and {_counted(facts.automated, 'automated account')}"
        lines = [
            f"{repository[0]} ({repository[1]}), since {since} to {tip[:7]}:",
            f"{_counted(facts.commits, 'commit')} by {who}, "
            f"{facts.first.isoformat()} to {facts.last.isoformat()}"
            + (f"; {facts.co_authored:,} credit a co-author." if facts.co_authored else "."),
            f"Most changed areas: {listed([f'{a} {n:,}' for a, n in facts.areas])}.",
            f"File changes by type: {listed([f'{t} {n:,}' for t, n in facts.file_types])}.",
            f"Files added: {facts.files_added:,}.",
        ]
        if facts.active_again:
            lines.append(
                f"Active again after {QUIET_DAYS} or more quiet days: "
                f"{listed(list(facts.active_again))}."
            )
        if tags:
            lines.append(f"Tags in the range: {listed(tags)}.")
        lines.append(f"Next: reveille brief --from {tip[:12]}")
        lines.append(_NOTICE)
        return "\n".join(lines) + "\n"

    @staticmethod
    def state_text(
        state: RepositoryState,
        *,
        name: str,
        history_replaced: bool,
        output_format: str,
        limit: int,
    ) -> str:
        """Render a repository's present state as JSON or plain lines (ADR 0024).

        Args:
            state: What was read.
            name: The repository's directory name.
            history_replaced: Whether replace refs or a graft file are present and not followed.
            output_format: "json", "text", "markdown" or "line".
            limit: The most paths any list carries.

        Returns:
            The state; text stays under 2 KB.
        """
        if output_format == "json":
            return json.dumps(_state_document(state, name, history_replaced, limit), indent=2)
        if output_format == "markdown":
            return _state_markdown(state, name, history_replaced, limit)
        if output_format == "line":
            return _state_line(state, name)
        return "\n".join(_state_lines(state, name, history_replaced, limit)) + "\n"

    def render_csv(self, data: ReportData, output_path: Path) -> Path:
        """Serialise the ranked contributor table to a UTF-8 CSV file with a BOM.

        The BOM makes Excel on Windows read the encoding correctly.

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
        text = self.csv_text(data)
        try:
            # BOM for spreadsheets; stdout output (csv_text) carries none.
            _write_replacing(resolved, text, encoding="utf-8-sig")
        except OSError as exc:
            raise OutputPathError(f"Failed to write CSV report to '{resolved}': {exc}") from exc
        return resolved

    def csv_text(self, data: ReportData) -> str:
        """Serialise the contributor table as CSV text, for a file or for stdout.

        Args:
            data: The complete structured report dataset.

        Returns:
            The CSV document, without a byte-order mark.
        """
        # Ranking columns are omitted when ranking is off (ADR 0010); `rank`
        # stays as the row ordinal.
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
            # Credited by Co-authored-by trailers; not authorship (ADR 0014).
            "co_authored_commits",
        ]
        if ranked:
            fieldnames[3:3] = ["designation", "tier"]
            fieldnames += ["composite_score", "percentile"]

        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for i, r in enumerate(data.ranked_contributors[: data.provenance.limit]):
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
                "co_authored_commits": r.stats.co_authored_commits,
            }
            if ranked:
                row["designation"] = _neutralise_csv_cell(r.tier_designation)
                row["tier"] = r.tier
                row["composite_score"] = r.composite_score
                row["percentile"] = r.percentile
            writer.writerow(row)
        return buffer.getvalue()

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
        # `min_commits` filters the listing, not the figures (ADR 0011);
        # distribution figures count people, not automated accounts (ADR 0017).
        everyone = _population(data)
        population = [stats.commit_count for stats in _people(data)]
        automated = [s for s in everyone if is_automated(s.name, s.email)]
        return {
            "commit_concentration": _compute_commit_concentration(population),
            # Two places: a third decimal would imply unwarranted precision.
            "gini_coefficient": round(gini_coefficient(population), 2),
            # The sample maximum is (n-1)/n, so the reader needs the ceiling.
            "gini_ceiling": _ceiling_text(len(population)),
            # Every contributor, not the table's row count.
            "population_size": len(everyone),
            # Who the distribution figures describe, and who they omit (ADR 0017).
            "people": len(population),
            "automated_accounts": len(automated),
            "automated_commits": sum(s.commit_count for s in automated),
            "contributors_below_threshold": len(data.suppressed_contributors),
            # What the hotspot ranking leaves out, stated beside it.
            "generated_files": generated_churn(data.file_stats)[0],
            "generated_lines": generated_churn(data.file_stats)[1],
            "longest_inactive_streak": longest_quiet_run(data.commits),
            # Text alternative for the heatmap, which has no figure to tabulate.
            "heatmap_summary": _summarise_activity(data.commits),
            # Rule-based findings (domain/summary.py), measured against the
            # window's end so dormancy can be reported.
            "findings": summarise(data.commits, _people(data), today=data.metadata.analysis_until),
            # Who changed each area; empty unless --area-authors (ADR 0013).
            "areas": _area_statements(data),
            # Co-authorship beside authorship (ADR 0014).
            "co_authored_any": any(r.stats.co_authored_commits for r in data.ranked_contributors),
            "co_authors_named": [
                c
                for c in data.co_authors_only
                if c.co_authored_commits >= data.provenance.min_commits
            ],
            "co_authors_unnamed": sum(
                1
                for c in data.co_authors_only
                if c.co_authored_commits < data.provenance.min_commits
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

        Each value is Plotly figure JSON, or 'null' when data is insufficient;
        the heatmap's is a daily-count payload instead.

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
            "lorenz": _build_lorenz_chart([stats.commit_count for stats in _people(data)]),
            "commit_size": _build_commit_size_chart(data.commits),
            "hotspots": _build_hotspot_chart(data.file_stats),
            "extensions": _build_extension_chart(data.file_stats),
        }


# ------------------------------------------------------------------
# Chart construction functions
# ------------------------------------------------------------------


def _ceiling_text(population: int) -> str:
    """Format the largest Gini a population of this size can reach, (n-1)/n.

    Truncated to three places where two would round to a misleading "1.00".

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


#: Stated in every output that carries figures; one copy, so they cannot drift.
_NOTICE = (
    "Computed from Git history by fixed rules, offline. History can be incomplete or "
    "wrong (rewritten, shallow, misdated, split identities); check before "
    "relying on it for a decision."
)


def _listed_co_authors(data: ReportData) -> list[CoAuthor]:
    """Co-authors-only at or above the listing threshold (ADR 0011, 0014)."""
    return [c for c in data.co_authors_only if c.co_authored_commits >= data.provenance.min_commits]


#: Geometry of the profile flower (ADR 0016), in SVG user units.
_FLOWER_CENTRE = 220.0
_FLOWER_RADIUS = 120.0
_FLOWER_LABEL_RADIUS = 140.0
#: Degrees of each petal's wedge; the remainder is gap, keeping petals separate.
_PETAL_SPAN = 44.0


def _profile_flower(profile: list[ProfileAxis]) -> list[dict[str, Any]]:
    """Lay out the profile as separate petals: geometry only, no colour.

    Each petal's length is its share (centre 0%, rim 100%), over a full-length
    track, with an arc at the expected value where there is one.

    Args:
        profile: The axes, in their fixed order.

    Returns:
        One dictionary per petal with SVG path data and label placement.
    """
    if not profile:
        return []
    step = 360.0 / len(profile)

    def point(radius: float, degrees: float) -> str:
        angle = math.radians(degrees)
        x = _FLOWER_CENTRE + radius * math.cos(angle)
        y = _FLOWER_CENTRE + radius * math.sin(angle)
        return f"{x:.1f} {y:.1f}"

    def wedge(radius: float, start: float, end: float) -> str:
        return (
            f"M {_FLOWER_CENTRE:.1f} {_FLOWER_CENTRE:.1f} L {point(radius, start)} "
            f"A {radius:.1f} {radius:.1f} 0 0 1 {point(radius, end)} Z"
        )

    petals = []
    for index, axis in enumerate(profile):
        middle = -90.0 + index * step
        start, end = middle - _PETAL_SPAN / 2, middle + _PETAL_SPAN / 2
        length = _FLOWER_RADIUS * max(0.0, min(axis.value, 1.0))
        expected = None
        if axis.expected is not None:
            radius = _FLOWER_RADIUS * max(0.0, min(axis.expected, 1.0))
            expected = (
                f"M {point(radius, start)} A {radius:.1f} {radius:.1f} 0 0 1 {point(radius, end)}"
            )
        cosine = math.cos(math.radians(middle))
        label_x, label_y = point(_FLOWER_LABEL_RADIUS, middle).split()
        petals.append(
            {
                "name": axis.name,
                "percent": f"{axis.value * 100:.0f}%",
                "track": wedge(_FLOWER_RADIUS, start, end),
                "petal": wedge(length, start, end) if length >= 0.5 else "",
                "expected": expected,
                "label_x": label_x,
                "label_y": label_y,
                "anchor": "middle" if abs(cosine) < 0.3 else ("start" if cosine > 0 else "end"),
            }
        )
    return petals


def _truncated(items: Sequence[object], limit: int | None) -> bool:
    """Return whether bounding `items` to `limit` leaves any out."""
    return limit is not None and len(items) > limit


def _area_statements(data: ReportData) -> list[AreaStatement]:
    """Describe who changed each area, when the report asked for it.

    Args:
        data: The complete report dataset.

    Returns:
        One statement per area shown, or none when the section is off.
    """
    if not data.areas:
        return []
    names = {s.email.lower(): s.name for s in _population(data)}
    listed = {r.stats.email.lower() for r in data.ranked_contributors}
    return describe_areas(data.areas, names, listed, data.metadata.analysis_until)


def _population(data: ReportData) -> list[ContributorStats]:
    """Every contributor in the repository, listed or not.

    ADR 0011: `min_commits` chooses who is listed; every figure describes the
    whole repository, from this one definition. Charts naming people use only
    the listed.

    Args:
        data: The complete report dataset.

    Returns:
        Listed contributors followed by those held back by `min_commits`.
    """
    return [ranked.stats for ranked in data.ranked_contributors] + list(
        data.suppressed_contributors
    )


def _counted(n: int, singular: str) -> str:
    """Return "1 thing" or "N things"."""
    return f"{n:,} {singular}" if n == 1 else f"{n:,} {singular}s"


def _people(data: ReportData) -> list[ContributorStats]:
    """The population the distribution figures describe: people only (ADR 0017).

    `_population` less automated accounts, so every figure describes the same people.

    Args:
        data: The complete report dataset.

    Returns:
        Every contributor, listed or not, that is not an automated account.
    """
    return [s for s in _population(data) if not is_automated(s.name, s.email)]


def _contributor_labels(ranked: list[RankedContributor]) -> dict[str, str]:
    """Map each contributor's email to a label unique within the report.

    Names are not unique (ADR 0002), and Plotly merges repeated category labels.
    A repeated name carries its address; a unique one is used as it is.

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


#: Axis pairs to read a table from, per trace type, so the table cannot drift.
_TABLE_AXES: dict[str, tuple[str, str]] = {
    "bar": ("x", "y"),
    "scatter": ("x", "y"),
    "pie": ("labels", "values"),
}

#: Column headings per chart's table: the category first, then series names.
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

    States what a sighted reader takes from the picture: volume, span, peak.

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
        f"{_counted(len(commits), 'commit')} across {_counted(len(per_day), 'active day')}, "
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
    """Return a tabular equivalent of a chart, for assistive technology (WCAG 1.1.1).

    Rows are read back from the emitted specification, so they match the chart.

    Args:
        chart: The chart's id, used to look up its column headings.
        specification: That chart's Plotly JSON.

    Returns:
        A mapping with `columns` and `rows`, or empty when there is nothing.
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

    Quiet weeks are drawn as zero, not bridged by a line implying activity.

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
        window: The analysis window's first and last day; else the commits' span.

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
            # One point draws no line; a marker shows it.
            mode="lines+markers" if len(sorted_weeks) == 1 else "lines",
            marker={"size": 8},
            fill="tozeroy",
            line={"color": _CATEGORICAL_PALETTE[0], "width": 2},
            fillcolor=_translucent(_CATEGORICAL_PALETTE[0], 0.10),
            hovertemplate="Week of %{x|%Y-%m-%d}<br>Commits: %{y:,}<extra></extra>",
        )
    )
    layout = _base_layout()
    # A date axis, so ticks space themselves by month or year.
    layout["xaxis"] = _week_axis(sorted_weeks)
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

    One trace per listed contributor, in ranked order, at most `_MAX_SERIES`:
    beyond that colours would repeat. Everyone remains in the table and heatmap.

    Args:
        commits: All commits in the analysis window.
        ranked: Ranked contributor list in composite score order.
        window: The analysis window, as for `_build_timeline_chart`.

    Returns:
        Plotly figure JSON, or 'null' for fewer than two contributors or no commits.
    """
    if not commits or len(ranked) < 2:
        return "null"

    shown = ranked[:_MAX_SERIES]
    # Over the full list: ambiguity is relative to everyone in the report.
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
                mode="lines+markers" if len(all_weeks) == 1 else "lines",
                marker={"size": 8},
                name=labels[r.stats.email.lower()],
                line={
                    "color": _CATEGORICAL_PALETTE[i],
                    "width": 2,
                    # A dash as well as a hue: WCAG 1.4.1, not colour alone.
                    "dash": _LINE_DASHES[i % len(_LINE_DASHES)],
                },
                hovertemplate="Week of %{x|%Y-%m-%d}<br>Commits: %{y:,}<extra></extra>",
            )
        )

    layout = _base_layout()
    # A date axis, so ticks space themselves by month or year.
    layout["xaxis"] = _week_axis(all_weeks)
    layout["showlegend"] = True
    layout["legend"] = {"orientation": "h", "y": 1.12, "x": 0}
    fig.update_layout(
        **layout,
        xaxis_title="Week",
        yaxis_title="Commits",
        height=320,
    )
    return _to_json(fig)


def _week_axis(weeks: list[str]) -> dict[str, Any]:
    """Return the x axis for a weekly timeline.

    A single week gets a week of padding either side, or Plotly ticks milliseconds.

    Args:
        weeks: The ISO dates of the weeks drawn, in order.

    Returns:
        A Plotly axis definition.
    """
    axis: dict[str, Any] = {"type": "date", "automargin": True}
    if len(weeks) == 1:
        week = datetime.date.fromisoformat(weeks[0])
        span = datetime.timedelta(days=7)
        axis["range"] = [(week - span).isoformat(), (week + span).isoformat()]
        axis["tickformat"] = "%b %-d, %Y"
    return axis


def _build_heatmap_data(
    commits: list[Commit],
    ranked_contributors: list[RankedContributor],
    analysis_since: datetime.date,
    analysis_until: datetime.date,
) -> str:
    """Build a compact daily commit-count payload for client-side heatmap rendering.

    Keys: `years`; `contributors`, `{email, name}` with "__aggregated__" first;
    `daily_counts`, email to ISO date to count. The client draws the grid.

    Args:
        commits: All commits in the analysis window.
        ranked_contributors: Contributors in rank order, for the dropdown.
        analysis_since: Start of the analysis window.
        analysis_until: End of the analysis window.

    Returns:
        JSON safe to embed in an application/json script block.
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
        # The grid draws these bounds, so days outside the window are not zeros.
        "since": analysis_since.isoformat(),
        "until": analysis_until.isoformat(),
        "contributors": contributors,
        "daily_counts": daily_counts,
    }
    return _script_safe(json.dumps(payload))


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

    Contributors beyond _PIE_MAX_SLICES, and unlisted ones, go into 'Other
    Contributors', so slices are shares of every commit (ADR 0011).

    Args:
        ranked: Ranked contributor list sorted by composite score descending.
        unlisted_commits: Commits by contributors below the listing threshold.

    Returns:
        Plotly figure JSON, or 'null' if fewer than two slices would be drawn.
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
            # The donut shrinks to fit outside labels on narrow screens.
            automargin=True,
            marker={"colors": _pie_colors(len(labels), has_other=labels[-1] == _OTHER_LABEL)},
            hovertemplate="%{label}<br>Commits: %{value:,}<br>%{percent}<extra></extra>",
            sort=False,
        )
    )
    layout = _base_layout()
    layout["showlegend"] = False
    layout["margin"] = {"l": 20, "r": 20, "t": 40, "b": 20}
    fig.update_layout(**layout, height=320)
    return _to_json(fig)


def _build_commit_size_chart(commits: list[Commit]) -> str:
    """Build a histogram of change size per commit, on a log-spaced scale.

    Lines added plus deleted per commit (relative churn, Nagappan & Ball, ICSE
    2005), pooled across contributors. Log-spaced, since sizes are heavily skewed.

    Args:
        commits: All commits in the analysis window.

    Returns:
        A Plotly figure JSON string, or 'null' if commits is empty.
    """
    if not commits:
        return "null"

    # The first bin starts at zero: an empty or binary-only commit counts no line.
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

    # With log-spaced bins the tallest bar is not the median, so mark it.
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

    The churn axis of hotspot analysis (Tornhill, 2013) only: Reveille never
    reads file content, so frequent change marks a file to look at, not a fault.

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
            # The label sits past the longest bar; clipping would cut it.
            cliponaxis=False,
        )
    )
    layout = _base_layout()
    layout["margin"] = {**layout["margin"], "r": 60}
    # Below 560 px the template shows shortened paths, marked by an ellipsis,
    # rather than letting Plotly clip them; hover and the table keep full paths.
    layout["meta"] = {
        "narrow_layout": {
            "yaxis": {
                "tickmode": "array",
                "tickvals": paths,
                "ticktext": [_shorten_path(p) for p in paths],
            },
            # Three ticks and a short title fit a phone.
            "xaxis": {"nticks": 3, "title": {"text": "Lines changed"}},
        }
    }
    fig.update_layout(
        **layout,
        xaxis_title="Lines changed (added + deleted)",
        height=max(280, min(len(ranked) * 30 + 90, _MAX_CHART_HEIGHT)),
    )
    return _to_json(fig)


def _shorten_path(path: str, limit: int = 26) -> str:
    """Return a path short enough for a phone's axis, marked where cut.

    Whole trailing components are kept, so the file name survives.

    Args:
        path: A repository-relative path, already sanitised for display.
        limit: The longest label to return.

    Returns:
        The path unchanged if it fits, otherwise "…/" and its tail.
    """
    if len(path) <= limit:
        return path
    kept: list[str] = []
    for part in reversed(path.split("/")):
        candidate = "/".join([part, *kept])
        if len(candidate) + 2 > limit:
            break
        kept.insert(0, part)
    if not kept:
        return "…" + path[-(limit - 1) :]
    return "…/" + "/".join(kept)


def _build_extension_chart(files: list[FileStats]) -> str:
    """Build a bar chart of churn totalled by file extension, naming nobody.

    Args:
        files: Per-path activity for the analysis window.

    Returns:
        A Plotly figure JSON string, or 'null' if there is nothing to show.
    """
    breakdown = extension_breakdown(files, limit=8)
    if not breakdown:
        return "null"

    # Plotly renders some HTML in labels; an extension is untrusted text.
    labels = [_sanitise_chart_label(label) for label, _ in breakdown]
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
    # Taller on a phone, where rotated labels need room.
    layout["meta"] = {"narrow_layout": {"height": 360}}
    fig.update_layout(
        **layout,
        xaxis_title="File type",
        yaxis_title="Lines changed",
        height=280,
    )
    return _to_json(fig)


def _build_lorenz_chart(counts: list[int]) -> str:
    """Build a Lorenz curve of commit distribution across contributors.

    The curve bows below the equality diagonal as activity concentrates. It names
    nobody, which is why it is in the default report. The Gini is shown by the
    template's heading, where it cannot overlap the legend.

    Args:
        counts: Commit count per contributor, any order, unlisted included.

    Returns:
        Plotly figure JSON, or 'null' for fewer than two contributors.
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
    """Count the fewest contributors who between them authored half the commits.

    Not a bus factor: that measures knowledge concentration, a property of line
    ownership, not of commit counts. Counts include unlisted contributors.

    Args:
        counts: Commit count per contributor, in any order.

    Returns:
        An integer in [1, len(counts)], or 0 when `counts` is empty or sums to zero.
    """
    if not counts:
        return 0
    total = sum(counts)
    if total == 0:
        return 0
    threshold = total * 0.5
    cumulative = 0
    # The loop always returns (guarded above); the tail satisfies mypy --strict.
    for position, count in enumerate(sorted(counts, reverse=True), start=1):  # pragma: no branch
        cumulative += count
        if cumulative >= threshold:
            return position
    return len(counts)  # pragma: no cover - unreachable, see above


# ------------------------------------------------------------------
# Chart helper utilities
# ------------------------------------------------------------------


# Leading characters that make a spreadsheet read a cell as a formula; a
# leading tab or carriage return is skipped, exposing what follows.
_CSV_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


def _write_replacing(path: Path, text: str, *, encoding: str) -> None:
    """Write `text` to a new file and move it over `path`.

    Replacing the name, not writing in place, leaves other hard links (such as
    one to `.git/HEAD`) untouched. A new report is 0o600, since it names people;
    an existing one keeps its mode. The temporary file is removed on failure.

    Args:
        path: The resolved output path.
        text: What to write. Newlines are written as given.
        encoding: The text encoding, `utf-8-sig` for a CSV with a BOM.

    Raises:
        OSError: If the file cannot be created, written or moved.
    """
    try:
        kept_mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        kept_mode = None
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        if kept_mode is not None:
            temporary.chmod(kept_mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _assert_not_symlink(output_path: Path) -> None:
    """Refuse to write a report through a symbolic link.

    An untrusted config could otherwise aim the report at any file. Must run on
    the path as given: a resolved path is never a symlink.

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

    Names and addresses are attacker-controlled; a leading apostrophe makes a
    spreadsheet treat the cell as text. Free-text columns only.

    Args:
        value: A free-text cell value derived from repository metadata.

    Returns:
        The value, prefixed with an apostrophe if it would read as a formula.
    """
    if value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def _script_safe(text: str) -> str:
    r"""Escape JSON for embedding in an HTML `<script>` element.

    Every `<` becomes `\u003c`, not just `</`: `<!--<script` would also break
    the block. JSON holds `<` only inside strings, so this is always valid.

    Args:
        text: A JSON document.

    Returns:
        The same document with no `<` in it.
    """
    return text.replace("<", "\\u003c")


def _sanitise_chart_label(value: str) -> str:
    """Strip HTML tags, null bytes, and surrounding whitespace from a chart label.

    Labels come from commit metadata, and Plotly renders some HTML in them.

    Args:
        value: The raw string to sanitise.

    Returns:
        The sanitised string.
    """
    value = _SCRIPT_BLOCK_RE.sub("", value)
    value = _HTML_TAG_RE.sub("", value)
    value = value.replace("\x00", "")
    return value.strip()


def _aggregate_pie_data(
    items: list[tuple[str, int]],
) -> tuple[list[str], list[int]]:
    """Aggregate ranked (label, value) pairs for pie chart rendering.

    Items beyond _PIE_MAX_SLICES are summed into 'Other Contributors'; order is kept.

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
        has_other: Whether the final slice is the "Other Contributors" residual.

    Returns:
        n hex colours, never repeated; the residual takes the reserved neutral.
    """
    if has_other and n >= 1:
        return [_CATEGORICAL_PALETTE[i] for i in range(n - 1)] + [_OTHER_SLICE_COLOUR]
    return [_CATEGORICAL_PALETTE[i] for i in range(n)]


# ------------------------------------------------------------------
# Layout helpers
# ------------------------------------------------------------------


def _base_layout() -> dict[str, Any]:
    """Return shared Plotly layout configuration for all charts.

    No theme colours: the client-side theme manager supplies them, re-plotting
    on toggle rather than using Plotly.relayout() (the template says why).

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
        # The top margin holds Plotly's toolbar (about 26 px).
        "margin": {"l": 60, "r": 30, "t": 40, "b": 50},
        # automargin grows margins to fit tick labels and titles. Numbers are
        # in full with separators, as the rest of the report writes them.
        "xaxis": {"automargin": True, "separatethousands": True, "exponentformat": "none"},
        "yaxis": {"automargin": True, "separatethousands": True, "exponentformat": "none"},
        "showlegend": False,
        "modebar": {"remove": ["logo"]},
    }


def _to_json(fig: go.Figure) -> str:
    r"""Serialise a Plotly figure to a JSON specification string.

    Theme-dependent colours are stripped here, where every chart passes, since
    a spec renders under both themes; the theme manager is their only source.
    Every `<` is escaped (see `_script_safe`).

    Args:
        fig: A fully configured Plotly Figure instance.

    Returns:
        A JSON string containing 'data' and 'layout' keys.
    """
    figure_json: str = fig.to_json() or "{}"
    raw: dict[str, Any] = json.loads(figure_json)
    layout = raw.get("layout", {})

    # Plotly.js has the same default template client-side; the serialised copy
    # is most of each spec and carries light-theme colours.
    layout.pop("template", None)

    _strip_theme_colours(layout)
    raw["layout"] = layout
    return _script_safe(json.dumps(raw))


#: Paths of nested layout keys whose colour differs between themes; a test
#: asserts no emitted spec contains them.
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

#: Axis-local colour keys, stripped from every axis (matched by prefix: `xaxis2`).
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


def _listed(items: tuple[str, ...] | list[str], limit: int) -> str:
    """Join at most `limit` items, saying how many more there are."""
    rest = len(items) - limit
    shown = ", ".join(items[:limit])
    return f"{shown} and {rest:,} more" if rest > 0 else shown


def _state_document(
    state: RepositoryState, name: str, history_replaced: bool, limit: int
) -> dict[str, Any]:
    """Build the `state` JSON document (ADR 0024)."""

    def bounded(items: tuple[str, ...]) -> dict[str, Any]:
        return {"total": len(items), "truncated": len(items) > limit, "list": list(items[:limit])}

    upstream = (
        {
            "name": state.upstream,
            "ahead": state.ahead,
            "behind": state.behind,
            "as_of": "last fetch",
        }
        if state.upstream
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "document": "state",
        "repository": {"name": name, "bare": state.bare, "shallow": state.shallow},
        "branch": state.branch,
        "head": state.head,
        "last_commit_date": state.last_commit.isoformat() if state.last_commit else None,
        "upstream": upstream,
        "operation_in_progress": state.operation,
        "clean": state.clean,
        "conflicted": bounded(state.conflicted),
        "staged": bounded(state.staged),
        "modified": bounded(state.modified),
        "deleted": bounded(state.deleted),
        "renamed": bounded(state.renamed),
        "untracked": bounded(state.untracked),
        "stashes": state.stashes,
        "worktrees": [
            {"path": w.path, "branch": w.branch, "locked": w.locked, "prunable": w.prunable}
            for w in state.worktrees[:limit]
        ],
        "worktrees_total": len(state.worktrees),
        "branches": {
            "local": state.branches,
            "merged_into_head": state.branches_merged,
            "quiet": state.branches_quiet,
            "quiet_days": QUIET_BRANCH_DAYS,
        },
        "latest_tag": state.latest_tag,
        "commits_since_tag": state.commits_since_tag,
        "history_replaced_not_followed": history_replaced,
        "filters_not_run": list(state.filters_not_run),
        "working_tree_read": not (state.bare or state.working_tree_unread),
        "notice": _NOTICE,
    }


def _state_lines(
    state: RepositoryState, name: str, history_replaced: bool, limit: int
) -> list[str]:
    """Build the `state` text, one fact per line, under 2 KB."""
    where = f"on {state.branch}" if state.branch else "detached"
    if state.head is None:
        where += ", no commits yet"
    else:
        day = state.last_commit.isoformat() if state.last_commit else "?"
        where += f" ({state.head[:7]}, {day})"
    lines = [f"{name}: {where}."]
    if state.upstream:
        lines.append(
            f"Tracking {state.upstream}: {state.ahead or 0:,} ahead, "
            f"{state.behind or 0:,} behind, as of the last fetch."
        )
    if state.operation:
        lines.append(f"In progress: {state.operation}.")
    if state.conflicted:
        lines.append(f"Conflicted: {_listed(state.conflicted, limit)}.")
    lines.extend(_working_tree_lines(state, limit))
    extra = ["1 stash" if state.stashes == 1 else f"{state.stashes:,} stashes"]
    if len(state.worktrees) > 1:
        others = [f"{w.path} ({w.branch or 'detached'})" for w in state.worktrees[1:]]
        extra.append(f"{len(others):,} other worktrees: {_listed(others, limit)}")
    lines.append("; ".join(extra) + ".")
    lines.append(
        f"Branches: {state.branches:,} local, {state.branches_merged:,} merged into this commit, "
        f"{state.branches_quiet:,} with no commit in {QUIET_BRANCH_DAYS} days before it."
    )
    if state.latest_tag:
        lines.append(
            f"Latest tag: {state.latest_tag}, {state.commits_since_tag or 0:,} commits since. "
            f"Next: reveille brief --from {state.latest_tag}"
        )
    if state.shallow:
        lines.append("Shallow clone: only part of the history is present.")
    if history_replaced:
        lines.append("Replace refs or a graft file are present and not followed.")
    if state.filters_not_run:
        lines.append(
            f"Not run: the content filters this repository's own config names "
            f"({_listed(state.filters_not_run, limit)}); files they cover may show as modified."
        )
    lines.append(_NOTICE)
    return lines


def _working_tree_lines(state: RepositoryState, limit: int) -> list[str]:
    """Say what is staged, modified and untracked, or that the tree is clean."""
    if state.bare:
        return ["Bare repository: no working tree."]
    if state.working_tree_unread:
        return [
            "Working tree: not compared. Git could not say which config defines its content "
            "filters, and comparing files could run one the repository names."
        ]
    if state.clean:
        return ["Working tree: clean."]
    counts = [
        (len(state.staged), "staged"),
        (len(state.modified), "modified"),
        (len(state.deleted), "deleted"),
        (len(state.renamed), "renamed"),
        (len(state.untracked), "untracked"),
    ]
    lines = ["Working tree: " + ", ".join(f"{n:,} {label}" for n, label in counts if n) + "."]
    for label, items in (
        ("Staged", state.staged),
        ("Modified", state.modified),
        ("Untracked", state.untracked),
    ):
        if items:
            lines.append(f"  {label}: {_listed(items, limit)}.")
    return lines


def _md(value: str) -> str:
    """Put repository text in a Markdown code span: shown literally, on one line.

    The fence is longer than any run of backticks inside, and CR and LF are shown
    as escapes, so a path, branch or tag name cannot add a heading, a link or HTML.
    """
    text = value.replace("\r", "\\r").replace("\n", "\\n")
    if not text:
        return "(empty)"
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _md_listed(
    items: list[str] | tuple[str, ...], limit: int, counts: dict[str, int] | None = None
) -> str:
    """Join at most `limit` code spans, with an optional count each, saying how many more."""
    shown = ", ".join(
        f"{_md(item)} {counts[item]:,}" if counts is not None else _md(item)
        for item in items[:limit]
    )
    rest = len(items) - limit
    return f"{shown} and {rest:,} more" if rest > 0 else shown


def _summary_markdown(document: dict[str, Any]) -> str:
    """Render the summary as Markdown for an issue, a pull request or a CI job summary."""
    repo, totals, measures = document["repository"], document["totals"], document["measures"]
    automated = (
        f" and {_counted(totals['automated_accounts'], 'automated account')}"
        if totals["automated_accounts"]
        else ""
    )
    lines = [
        f"### Summary: {_md(repo['name'])} ({_md(repo['analysed_branch'])}), "
        f"{repo['analysis_since']} to {repo['analysis_until']}",
        "",
        f"- **Commits:** {_counted(totals['commits'], 'commit').split(' ', 1)[0]} by "
        f"{_counted(totals['authors'], 'author')}{automated}",
        f"- **Gini:** {measures['gini_coefficient']:.2f}; longest quiet run "
        f"{_counted(measures['longest_quiet_run_days'], 'day')}",
        *(f"- {finding['headline']}" for finding in document["findings"]),
        "",
        f"> {document['notice']}",
    ]
    return "\n".join(lines) + "\n"


def _brief_markdown(
    facts: Brief,
    repository: tuple[str, str],
    point: tuple[str, str | None],
    tip: str,
    tags: list[str],
    limit: int,
) -> str:
    """Render a brief as Markdown (ADR 0022)."""
    named, commit = point
    since = f"{_md(named)} ({_md(commit[:7])})" if commit is not None else _md(named)
    who = "1 person" if facts.people == 1 else f"{facts.people:,} people"
    if facts.automated:
        who += f" and {_counted(facts.automated, 'automated account')}"
    co = f"; {facts.co_authored:,} credit a co-author" if facts.co_authored else ""
    lines = [
        f"### Brief: {_md(repository[0])} ({_md(repository[1])}), since {since} to {_md(tip[:7])}",
        "",
        f"- **Commits:** {facts.commits:,} by {who}, {facts.first.isoformat()} to "
        f"{facts.last.isoformat()}{co}",
        f"- **Most changed areas:** {_md_listed([a for a, _ in facts.areas], limit, dict(facts.areas))}",
        "- **File changes by type:** "
        f"{_md_listed([t for t, _ in facts.file_types], limit, dict(facts.file_types))}",
        f"- **Files added:** {facts.files_added:,}",
    ]
    if facts.active_again:
        lines.append(
            f"- **Active again after {QUIET_DAYS} quiet days:** "
            f"{_md_listed(facts.active_again, limit)}"
        )
    if tags:
        lines.append(f"- **Tags in the range:** {_md_listed(tags, limit)}")
    lines += ["", f"Next: {_md(f'reveille brief --from {tip[:12]}')}", "", f"> {_NOTICE}"]
    return "\n".join(lines) + "\n"


def _state_markdown(state: RepositoryState, name: str, history_replaced: bool, limit: int) -> str:
    """Render a repository's present state as Markdown (ADR 0024)."""
    where = _md(state.branch) if state.branch else "detached"
    if state.head is None:
        where += ", no commits yet"
    else:
        day = state.last_commit.isoformat() if state.last_commit else "?"
        where += f" at {_md(state.head[:7])} ({day})"
    lines = [f"### State: {_md(name)}", "", f"- **Branch:** {where}"]
    if state.upstream:
        lines.append(
            f"- **Upstream:** {_md(state.upstream)}, {state.ahead or 0:,} ahead, "
            f"{state.behind or 0:,} behind, as of the last fetch"
        )
    if state.operation:
        lines.append(f"- **In progress:** {state.operation}")
    if state.conflicted:
        lines.append(f"- **Conflicted:** {_md_listed(state.conflicted, limit)}")
    tree = _working_tree_lines(state, limit)[0].removeprefix("Working tree: ").rstrip(".")
    lines.append(f"- **Working tree:** {tree}")
    for label, items in (
        ("Staged", state.staged),
        ("Modified", state.modified),
        ("Untracked", state.untracked),
    ):
        if items and not (state.bare or state.working_tree_unread):
            lines.append(f"  - {label}: {_md_listed(items, limit)}")
    lines.append(f"- **Stashes:** {state.stashes:,}")
    if len(state.worktrees) > 1:
        others = [f"{w.path} ({w.branch or 'detached'})" for w in state.worktrees[1:]]
        lines.append(f"- **Other worktrees:** {_md_listed(others, limit)}")
    lines.append(
        f"- **Branches:** {state.branches:,} local, {state.branches_merged:,} merged into this "
        f"commit, {state.branches_quiet:,} with no commit in {QUIET_BRANCH_DAYS} days before it"
    )
    if state.latest_tag:
        lines.append(
            f"- **Latest tag:** {_md(state.latest_tag)}, {state.commits_since_tag or 0:,} commits "
            f"since; next: {_md(f'reveille brief --from {state.latest_tag}')}"
        )
    lines += [*_state_markdown_notes(state, history_replaced, limit), "", f"> {_NOTICE}"]
    return "\n".join(lines) + "\n"


def _state_markdown_notes(state: RepositoryState, history_replaced: bool, limit: int) -> list[str]:
    """The state's closing notes as Markdown bullets: filters not run, shallow, replaced."""
    notes = []
    if state.filters_not_run:
        notes.append(
            f"- **Not run:** content filters this repository's own config names "
            f"({_md_listed(state.filters_not_run, limit)}); files they cover may show as modified"
        )
    if state.shallow:
        notes.append("- Shallow clone: only part of the history is present.")
    if history_replaced:
        notes.append("- Replace refs or a graft file are present and not followed.")
    return notes


def _one_line(text: str) -> str:
    """End `text` with its only newline: a CR or LF inside a name is shown as an escape."""
    return text.replace("\r", "\\r").replace("\n", "\\n") + "\n"


def _state_line(state: RepositoryState, name: str) -> str:
    """Render a repository's present state as one line of counts, naming no path."""
    where = f"{name}: {state.branch or 'detached'}"
    where += f" {state.head[:7]}" if state.head else ", no commits yet"
    parts = [where]
    if state.upstream:
        parts.append(f"{state.ahead or 0:,} ahead, {state.behind or 0:,} behind")
    if state.operation:
        parts.append(f"{state.operation} in progress")
    if state.bare:
        parts.append("bare")
    elif state.working_tree_unread:
        parts.append("working tree not compared")
    elif state.clean:
        parts.append("clean")
    else:
        counts = [
            (len(state.conflicted), "conflicted"),
            (len(state.staged), "staged"),
            (len(state.modified), "modified"),
            (len(state.deleted), "deleted"),
            (len(state.renamed), "renamed"),
            (len(state.untracked), "untracked"),
        ]
        parts.append(", ".join(f"{n:,} {label}" for n, label in counts if n))
    if state.stashes:
        parts.append("1 stash" if state.stashes == 1 else f"{state.stashes:,} stashes")
    if state.latest_tag:
        parts.append(f"{state.latest_tag} +{state.commits_since_tag or 0:,}")
    if state.filters_not_run:
        parts.append(_counted(len(state.filters_not_run), "filter") + " not run")
    if state.shallow:
        parts.append("shallow")
    return _one_line("; ".join(parts))


def _brief_line(
    facts: Brief, repository: tuple[str, str], named: str, tip: str, tags: list[str]
) -> str:
    """Render a brief as one line of counts."""
    who = "1 person" if facts.people == 1 else f"{facts.people:,} people"
    parts = [
        f"{repository[0]} {repository[1]} since {named} to {tip[:7]}: "
        f"{_counted(facts.commits, 'commit')} by {who}"
    ]
    if facts.automated:
        parts.append(_counted(facts.automated, "automated account"))
    if facts.files_added:
        parts.append(f"{_counted(facts.files_added, 'file')} added")
    if tags:
        parts.append(_counted(len(tags), "tag"))
    return _one_line(", ".join(parts))
