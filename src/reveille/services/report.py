# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Application service for report generation.

Reads commits, aggregates and optionally ranks contributors, and renders HTML,
JSON or CSV. Imports no GitPython, Jinja2, Plotly or Typer; progress goes to a
`ProgressEvent` callback whose display is the CLI's decision.

"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import cast

from reveille import __version__
from reveille.adapters.git_reader import GitReader, find_repositories, is_repository
from reveille.adapters.renderer import Renderer
from reveille.config import ReportConfig
from reveille.domain.areas import who_changed
from reveille.domain.brief import describe_range
from reveille.domain.coauthors import co_authors_only
from reveille.domain.models import (
    SCHEMA_VERSION,
    AnalysisProvenance,
    Commit,
    ProgressEvent,
    RankedContributor,
    ReportData,
)
from reveille.domain.pseudonyms import hide_emails
from reveille.domain.ranking import rank_contributors
from reveille.domain.repositories import RepositoryActivity, describe_repository
from reveille.exceptions import (
    EmptyRepositoryError,
    NoRepositoryReadError,
    RepositoryError,
    ReveilleError,
)

_logger = logging.getLogger(__name__)


def generate_report(
    config: ReportConfig,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_notice: Callable[[str], None] | None = None,
) -> list[Path]:
    """Generate the report and write it to the configured output path.

    Args:
        config: Validated report configuration.
        on_progress: Called with a ProgressEvent at each stage boundary.
        on_notice: Called with one sentence per caveat about how the report was produced.

    Returns:
        The absolute paths of the written files.

    Raises:
        RepositoryError: If the target path is not a readable Git repository.
        EmptyRepositoryError: If no commits exist within the analysis window.
        OutputPathError: If the output file cannot be written.
        RenderError: If the HTML template fails to render.
    """
    report_data = build_report_data(config, on_progress, on_notice)
    _note_cut_csv(config, report_data, on_notice)
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


def report_text(
    config: ReportConfig,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_notice: Callable[[str], None] | None = None,
) -> str:
    """Generate the report and return it as text, for `--output -` (ADR 0015).

    Args:
        config: Validated report configuration; its output path is unused.
        on_progress: As for generate_report.
        on_notice: As for generate_report.

    Returns:
        The report in the configured format.
    """
    report_data = build_report_data(config, on_progress, on_notice)
    _note_cut_csv(config, report_data, on_notice)
    renderer = Renderer()
    if config.output_format == "json":
        return renderer.json_text(report_data)
    if config.output_format == "csv":
        return renderer.csv_text(report_data)
    return renderer.html_text(report_data)


def summary_text(
    config: ReportConfig,
    output_format: str,
    on_notice: Callable[[str], None] | None = None,
) -> str:
    """Summarise the repository, naming nobody, as JSON or text (ADR 0015).

    Reads no line counts, so it costs a fraction of a full report.

    Args:
        config: Validated configuration; output settings are unused.
        output_format: "json" or "text".
        on_notice: As for generate_report.

    Returns:
        The summary.
    """
    data = build_report_data(config, on_notice=on_notice, line_counts=False)
    return Renderer().summary_text(data, output_format)


def who_changed_text(
    config: ReportConfig,
    path: str,
    output_format: str,
    limit: int,
    on_notice: Callable[[str], None] | None = None,
) -> str:
    """State who changed one path in the window (ADR 0015).

    Reads only commits touching the path, without line counts, so it is fast.

    Args:
        config: Validated configuration; output settings are unused.
        path: A repository-relative path, file or directory.
        output_format: "json" or "text".
        limit: The most names any list carries.
        on_notice: As for generate_report.

    Returns:
        The answer.

    Raises:
        EmptyRepositoryError: If no commit in the window changed the path.
    """
    reader = GitReader(config.repo_path)
    tip = reader.resolve_head_sha(config.branch)
    cutoff = _today() if config.until is None and not config.deterministic else None
    try:
        commits = reader.read_commits(
            branch=config.branch,
            since=config.since,
            until=config.until,
            exclude_authors=config.exclude_authors,
            exclude_paths=config.exclude_paths,
            dated_until=cutoff,
            line_counts=False,
            path=path,
        )
    except EmptyRepositoryError as exc:
        raise EmptyRepositoryError(f"No commit in the analysis window changed '{path}'.") from exc
    if reader.commits_dated_after and cutoff is not None:
        _notify(
            on_notice,
            f"{_count(reader.commits_dated_after)} dated after {cutoff.isoformat()} and not counted.",
        )
    if reader.is_shallow():
        _notify(on_notice, "This is a shallow clone, so only the history it holds is analysed.")
    first = min(c.timestamp.date() for c in commits)
    window_end = cutoff if cutoff is not None else _resolve_window_end(config, commits)
    window = (max(config.since, first) if config.since else first, window_end)
    return Renderer.who_changed_text(
        who_changed(path, commits), window, output_format, limit, analysed_commit=tip
    )


def state_text(repo_path: Path, output_format: str, limit: int) -> str:
    """Say where a repository stands now, changing nothing (ADR 0024).

    Args:
        repo_path: The repository root.
        output_format: "json", "text", "markdown" or "line".
        limit: The most paths any list carries.

    Returns:
        The state.
    """
    reader = GitReader(repo_path)
    state = reader.read_state()
    replace_refs, graft_file = reader.history_not_followed()
    return Renderer.state_text(
        state,
        name=repo_path.name,
        history_replaced=bool(replace_refs or graft_file),
        output_format=output_format,
        limit=limit,
    )


def repositories_text(
    directory: Path,
    *,
    depth: int,
    days: int,
    until: datetime.date | None,
    exclude_authors: list[str],
    output_format: str,
    on_notice: Callable[[str], None] | None = None,
) -> str:
    """Give one row per repository under a directory, naming no one (ADR 0026).

    Args:
        directory: Where to search.
        depth: How many levels below it to search.
        days: The activity window's length, ending on `until`.
        until: The window's last day; today (UTC) if None.
        exclude_authors: Applied in every repository, as `summary` applies them.
        output_format: "text", "json", "markdown" or "csv".
        on_notice: As for generate_report.

    Returns:
        The answer.

    Raises:
        EmptyRepositoryError: If no repository is found.
        NoRepositoryReadError: If repositories were found and none could be read.
    """
    end = until if until is not None else _today()
    try:
        start = end - datetime.timedelta(days=days - 1)
    except OverflowError:
        start = datetime.date.min  # a window reaching past the calendar's first day
    found, unreadable = find_repositories(directory, depth)
    if unreadable:
        _notify(
            on_notice,
            "1 directory could not be listed and was not searched."
            if len(unreadable) == 1
            else f"{len(unreadable):,} directories could not be listed and were not searched.",
        )
    if not found:
        # `repos` searches below the directory, so a repository given is not a row.
        hint = (
            " It is a repository itself: give the directory that holds it, or run "
            "`reveille state` on it."
            if is_repository(directory)
            else " A larger --depth searches deeper."
        )
        raise EmptyRepositoryError(
            f"No Git repository found in '{directory}' within {depth} "
            f"{'level' if depth == 1 else 'levels'}.{hint}"
        )
    rows: list[RepositoryActivity] = []
    matched: set[str] = set()
    # Most of a row's time is spent waiting for Git, so rows are read side by
    # side. Each has its own reader, and so its own Git runner; rows, and the
    # warnings each gives, keep the order the repositories were found in.
    held = _HeldWarnings()

    def read_row(path: Path) -> tuple[RepositoryActivity, set[str], list[logging.LogRecord]]:
        with held.on_this_thread() as records:
            row, matched_here = _repository_row(
                path, path.relative_to(directory).as_posix(), start, end, days, exclude_authors
            )
        if row.reason is not None:
            row = replace(row, reason=_without_local_paths(row.reason, directory))
        return row, matched_here, records

    with held.installed(), ThreadPoolExecutor(max_workers=_repository_workers()) as pool:
        for row, matched_here, records in pool.map(read_row, found):
            rows.append(row)
            matched |= matched_here
            for record in records:
                logging.getLogger(record.name).handle(record)
    unmatched = [value for value in exclude_authors if value not in matched]
    if unmatched:
        _notify(
            on_notice,
            f"--exclude-author matched no commits in any repository for: {', '.join(unmatched)}",
        )
    answer = Renderer.repositories_text(
        rows, directory.name, (start, end), days, depth, output_format
    )
    # Every input failing is "could not run", not an answer (ADR 0028); the rows
    # still go out, because each says why.
    if all(row.status == "not_read" for row in rows):
        raise NoRepositoryReadError(
            "The 1 repository found could not be read; its row says why."
            if len(rows) == 1
            else f"None of the {len(rows):,} repositories found could be read; each row says why.",
            answer,
        )
    return answer


class _HeldWarnings(logging.Filter):
    """Holds back what a thread logs, so it can be given out later, in order.

    The warnings name no repository, so the order of the rows is what tells a
    reader which one each came from.
    """

    def __init__(self) -> None:
        """Hold nothing until a thread asks."""
        super().__init__()
        self._local = threading.local()

    @contextlib.contextmanager
    def installed(self) -> Iterator[None]:
        """Filter every handler a `reveille` record reaches, until the block ends.

        Yields:
            Nothing.
        """
        handlers: list[logging.Handler] = []
        logger: logging.Logger | None = logging.getLogger("reveille")
        while logger is not None:
            handlers.extend(logger.handlers)
            logger = logger.parent if logger.propagate else None
        for handler in handlers:
            handler.addFilter(self)
        try:
            yield
        finally:
            for handler in handlers:
                handler.removeFilter(self)

    @contextlib.contextmanager
    def on_this_thread(self) -> Iterator[list[logging.LogRecord]]:
        """Hold what this thread logs in the block.

        Yields:
            The records held, in the order they were logged.
        """
        records: list[logging.LogRecord] = []
        self._local.records = records
        try:
            yield records
        finally:
            self._local.records = None

    def filter(self, record: logging.LogRecord) -> bool:
        """Hold the record if its thread asked; pass it on otherwise.

        Args:
            record: What was logged.

        Returns:
            False for a record held, True for one to emit now.
        """
        records: list[logging.LogRecord] | None = getattr(self._local, "records", None)
        if records is None:
            return True
        if not records or records[-1] is not record:  # each handler sees it in turn; hold it once
            records.append(record)
        return False


def _repository_workers() -> int:
    """Return how many repositories `repos` reads at once.

    Returns:
        One per CPU, at most 4: each read in flight holds its own history in
        memory, and 8 or 16 were measured slower than 4 (commit a9ead3b).
    """
    return max(1, min(4, _usable_cpus() or 1))


def _usable_cpus() -> int | None:
    """Return how many CPUs this process may run on, not how many the machine has.

    A container or a CI job pinned to one CPU still sees every CPU in
    `os.cpu_count()`. The affinity mask is what the process may use; Python
    3.13 reads it as `os.process_cpu_count()`.

    Returns:
        The count, or None if it cannot be known.
    """
    counted = getattr(os, "process_cpu_count", None)
    if counted is not None:
        return cast("int | None", counted())
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count()


def _repository_row(
    path: Path,
    relative: str,
    start: datetime.date,
    end: datetime.date,
    days: int,
    exclude_authors: list[str],
) -> tuple[RepositoryActivity, set[str]]:
    """Read one repository's row, or say why it could not be read.

    Args:
        path: The repository.
        relative: Its path relative to the directory searched.
        start: The window's first day.
        end: The window's last day.
        days: The window's length.
        exclude_authors: The exclusion values.

    Returns:
        The row, and the exclusion values that matched something in it.
    """
    try:
        reader = GitReader(path)
        branch = reader.read_metadata(0, 0, start, end).analysed_branch
        in_window = _read_or_empty(reader, start, end, exclude_authors)
        last_commit: datetime.date | None
        if in_window:
            last_commit = max(c.timestamp.date() for c in in_window)
        elif exclude_authors:
            # Which earlier commit is the last one counted turns on who made it.
            history = _read_or_empty(reader, None, end, exclude_authors)
            last_commit = max((c.timestamp.date() for c in history), default=None)
        else:
            # Only a date is needed from the history before the window.
            last_commit = reader.last_commit_date(end)
        matched = set(reader.matched_exclusions)
        return (
            describe_repository(
                relative,
                None if branch == "HEAD" else branch,
                last_commit,
                in_window,
                end,
                days,
                shallow=reader.is_shallow(),
            ),
            matched,
        )
    except ReveilleError as exc:
        # The first sentence, with the repository's own path made relative.
        reason = str(exc).replace(str(path), relative).split(". ")[0].rstrip(".")
        return RepositoryActivity(relative, "not_read", reason=reason), set()


# An absolute path, POSIX or Windows, starting a word or after a quote or bracket.
# Reveille's messages quote paths, so a quoted one is taken whole, spaces and all.
_QUOTED_ABSOLUTE_PATH = re.compile(r"'(?:/|[A-Za-z]:[\\/])[^']*'")
_ABSOLUTE_PATH = re.compile(r"""(?:(?<=^)|(?<=[\s'"(]))(?:/|[A-Za-z]:[\\/])[^\s'")]*""")


def _without_local_paths(reason: str, directory: Path) -> str:
    """Return `reason` with paths under `directory` relative and any other absolute path hidden.

    A path on this machine can hold a login name, and the row is meant to be shared.
    """
    for root in {str(directory.resolve()), str(directory)}:
        reason = reason.replace(root + os.sep, "")
    reason = _QUOTED_ABSOLUTE_PATH.sub("'(a path outside the directory)'", reason)
    return _ABSOLUTE_PATH.sub("(a path outside the directory)", reason)


def _read_or_empty(
    reader: GitReader,
    since: datetime.date | None,
    until: datetime.date,
    exclude_authors: list[str],
) -> list[Commit]:
    """Read a window's commits without line counts, or none if it holds none."""
    try:
        return reader.read_commits(
            None, since, until, exclude_authors, line_counts=False, report_unmatched=False
        )
    except EmptyRepositoryError:
        return []


#: Areas whose earlier history is looked up for "active again", in one pass.
_MAX_AREAS_LOOKED_UP = 50


def brief_text(
    config: ReportConfig,
    from_revision: str | None,
    output_format: str,
    limit: int,
    on_notice: Callable[[str], None] | None = None,
) -> str:
    """Say what changed since a point the caller names, in counts (ADR 0022).

    The point is a revision (`from_revision`), read by ancestry, or a date
    (`config.since`). Reads names and statuses, never line counts.

    Args:
        config: Validated configuration; output settings are unused.
        from_revision: A tag, branch or commit; None for `config.since`, or, with
            neither, the latest tag reachable on the branch.
        output_format: "json", "text", "markdown" or "line".
        limit: The most entries any list carries.
        on_notice: As for generate_report.

    Returns:
        The brief.

    Raises:
        EmptyRepositoryError: If nothing changed after the point.
    """
    reader = GitReader(config.repo_path)
    if from_revision is None and config.since is None:
        # Settle the branch first, so "no tag" is never said for another reason.
        if config.branch is not None:
            reader.resolve_commit(reader.branch_revision(config.branch))
        elif reader.resolve_head_sha() is None:
            raise EmptyRepositoryError(f"Repository at '{config.repo_path}' contains no commits.")
        from_revision = reader.latest_tag(reader.branch_revision(config.branch))
        if from_revision is None:
            raise RepositoryError(
                "The branch has no tag to start from: give --from <revision> or --since <date>."
            )
        # Resolved as a tag: a tag named like a commit hash would resolve to that commit.
        from_commit: str | None = reader.resolve_commit(f"refs/tags/{from_revision}")
    else:
        from_commit = reader.resolve_commit(from_revision) if from_revision is not None else None
    # Between two commits no clock enters; a date point ends the window today, as summary does.
    cutoff = (
        _today()
        if from_commit is None and config.until is None and not config.deterministic
        else None
    )
    point = from_revision if from_revision is not None else str(config.since)
    try:
        commits = reader.read_commits(
            branch=config.branch,
            since=None if from_commit is not None else config.since,
            until=config.until,
            exclude_authors=config.exclude_authors,
            exclude_paths=config.exclude_paths,
            dated_until=cutoff,
            area_depth=config.area_depth,
            line_counts=False,
            from_commit=from_commit,
            name_status=True,
        )
    except EmptyRepositoryError as exc:
        # Each limit the caller set is named, since any of them can be the cause.
        limits = [f"up to {config.until} (--until)"] if config.until is not None else []
        limits += [
            f"with {flag} applied"
            for flag, used in (
                ("--exclude-author", config.exclude_authors),
                ("--exclude-path", config.exclude_paths),
            )
            if used
        ]
        raise EmptyRepositoryError(
            f"No commits since {point}{''.join(' ' + limit for limit in limits)}."
        ) from exc
    if reader.commits_dated_after and cutoff is not None:
        _notify(
            on_notice,
            f"{_count(reader.commits_dated_after)} dated after {cutoff.isoformat()} and not counted.",
        )
    if reader.is_shallow():
        _notify(on_notice, "This is a shallow clone, so only the history it holds is analysed.")
    tip = reader.resolve_head_sha(config.branch) or ""
    if from_commit is not None and not reader.is_ancestor(from_commit, tip):
        _notify(
            on_notice,
            f"{from_revision} is not an ancestor of the analysed branch; counted are the "
            "branch's commits not reachable from it.",
        )
    areas = sorted(reader.area_activity, key=lambda a: (-a.commits, a.area))
    previous = reader.last_changes_before(
        [a.area for a in areas[:_MAX_AREAS_LOOKED_UP]],
        config.branch,
        from_commit,
        config.since if from_commit is None else None,
    )
    facts = describe_range(commits, list(reader.file_stats), areas, reader.files_added, previous)
    tags = reader.tags_in_range(
        config.branch,
        from_commit,
        config.since if from_commit is None else None,
        config.until,
    )
    window = (facts.first, facts.last)
    metadata = reader.read_metadata(
        total_commits=facts.commits,
        unique_contributors=facts.people,
        analysis_since=window[0],
        analysis_until=window[1],
        branch=config.branch,
    )
    return Renderer.brief_text(
        facts,
        repository=(metadata.name, metadata.analysed_branch),
        point=(point, from_commit),
        tip=tip,
        tags=tags,
        output_format=output_format,
        limit=limit,
    )


def build_report_data(
    config: ReportConfig,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_notice: Callable[[str], None] | None = None,
    *,
    line_counts: bool = True,
) -> ReportData:
    """Read the repository and assemble everything a report states.

    Args:
        config: Validated report configuration.
        on_progress: As for generate_report.
        on_notice: As for generate_report.
        line_counts: Read per-file line counts; False when nothing about lines is stated.

    Returns:
        The complete report dataset, ready for any renderer.
    """
    _logger.debug("pipeline start: repo=%s", config.repo_path)
    reader = GitReader(config.repo_path)
    stage_start = time.monotonic()

    _emit(on_progress, "Reading commit history", 0.0)
    # A default window ends today; later-dated commits are left out of every
    # figure, stated, and never stretch the window. An explicit `--until` is
    # taken as asked; deterministic mode closes on the last commit (ADR 0008).
    cutoff = _today() if config.until is None and not config.deterministic else None
    commits = reader.read_commits(
        branch=config.branch,
        since=config.since,
        until=config.until,
        exclude_authors=config.exclude_authors,
        exclude_paths=config.exclude_paths,
        dated_until=cutoff,
        # Collected only when enabled: the section names people (ADR 0013).
        area_depth=config.area_depth if config.area_authors_enabled else None,
        line_counts=line_counts,
    )
    after_window = reader.commits_dated_after if cutoff is not None else 0
    if after_window and cutoff is not None:
        _notify(
            on_notice,
            f"{_count(after_window)} dated after {cutoff.isoformat()} and not counted. "
            f"Pass --until with a later date to include {'it' if after_window == 1 else 'them'}.",
        )

    window_end = cutoff if cutoff is not None else _resolve_window_end(config, commits)

    # The window starts at the first commit, however early `--since` was: days
    # before it are not quiet days. `requested_since` keeps what was asked for.
    first_commit = min(c.timestamp.date() for c in commits)
    window_start = max(config.since, first_commit) if config.since is not None else first_commit

    elapsed = time.monotonic() - stage_start
    stage_start = time.monotonic()

    _emit(on_progress, "Aggregating contributor statistics", elapsed, len(commits))
    # Aggregated over everybody, then split: `min_commits` decides who is
    # listed, not the population the figures (such as the Gini) describe.
    every_contributor = reader.aggregate_contributor_stats(
        commits=commits,
        min_commits=1,
    )
    contributor_stats = [
        stats for stats in every_contributor if stats.commit_count >= config.min_commits
    ]
    suppressed_contributors = [
        stats for stats in every_contributor if stats.commit_count < config.min_commits
    ]
    if suppressed_contributors and not contributor_stats:
        # Not a negative answer: the report is written, and its figures stand.
        busiest = max(stats.commit_count for stats in every_contributor)
        _notify(
            on_notice,
            f"No contributor has the {config.min_commits:,} commits --min-commits asks for "
            f"(the most is {busiest:,}), so the contributor table is empty. The figures "
            "still count everyone.",
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

    # Deterministic mode pins the timestamp to the analysed commit, as a
    # reproducible build pins to SOURCE_DATE_EPOCH.
    if config.deterministic:
        head_commit_time = max(c.timestamp for c in commits)
        metadata = replace(metadata, generated_at=head_commit_time)

    shallow = reader.is_shallow()
    if shallow:
        _notify(
            on_notice,
            "This is a shallow clone, so only the history it holds is analysed and "
            "the window starts where that history does. Run `git fetch --unshallow` "
            "for the full history.",
        )
    replace_refs, graft_file = reader.history_not_followed()
    if replace_refs or graft_file:
        present = " and ".join(
            part
            for part in (
                _plural_refs(replace_refs) if replace_refs else "",
                "a .git/info/grafts file" if graft_file else "",
            )
            if part
        )
        _notify(
            on_notice,
            f"This repository has {present}, which `git log` follows and Reveille does not, "
            "so the history reported is the one the commit hashes name.",
        )
    provenance = replace(
        _build_provenance(config, head_sha, reader.mailmap_applied),
        commits_dated_after_window=after_window,
        commits_unreadable=reader.commits_unreadable,
        merge_commits_excluded=reader.merges_excluded,
        shallow_clone=shallow,
        replace_refs_not_followed=replace_refs,
        graft_file_not_followed=graft_file,
        area_authors_enabled=config.area_authors_enabled,
        area_depth=config.area_depth if config.area_authors_enabled else None,
        limit=config.limit,
    )

    report_data = ReportData(
        metadata=metadata,
        provenance=provenance,
        ranked_contributors=ranked_contributors,
        commits=commits,
        file_stats=list(reader.file_stats),
        suppressed_contributors=suppressed_contributors,
        areas=list(reader.area_activity) if config.area_authors_enabled else [],
        co_authors_only=co_authors_only(commits),
    )
    if config.hide_emails:
        report_data = hide_emails(report_data)

    _logger.debug(
        "assembled report data: %d commits, %d contributors",
        len(commits),
        len(contributor_stats),
    )
    return report_data


def _emit(
    on_progress: Callable[[ProgressEvent], None] | None,
    stage: str,
    elapsed_seconds: float,
    items_processed: int | None = None,
) -> None:
    """Emit a progress event if anybody is listening.

    Args:
        on_progress: The optional callback.
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


def _note_cut_csv(
    config: ReportConfig, data: ReportData, on_notice: Callable[[str], None] | None
) -> None:
    """Say when --limit cut the CSV, which has nowhere to carry a total.

    Args:
        config: The configuration, for the format and the limit.
        data: The report dataset.
        on_notice: Where the sentence goes.
    """
    listed = len(data.ranked_contributors)
    if config.output_format == "csv" and config.limit is not None and listed > config.limit:
        _notify(
            on_notice,
            f"The CSV lists {config.limit:,} of {listed:,} contributors (--limit); "
            "the JSON states the totals.",
        )


def _notify(on_notice: Callable[[str], None] | None, message: str) -> None:
    """Pass a notice to the caller, if anybody is listening.

    Args:
        on_notice: The optional callback.
        message: One plain sentence.
    """
    if on_notice is not None:
        on_notice(message)


def _count(commits: int) -> str:
    """Return "1 commit is" or "N commits are", for a notice."""
    return "1 commit is" if commits == 1 else f"{commits:,} commits are"


def _resolve_window_end(config: ReportConfig, commits: list[Commit]) -> datetime.date:
    """Decide the closing date of the analysis window.

    Deterministic mode closes on the last commit, not today: today feeds the
    ranking's recency, so scores would change from day to day.

    Args:
        config: The validated report configuration.
        commits: The commits in the window, for their timestamps.

    Returns:
        An explicit `--until`, else the last commit date if deterministic, else today.
    """
    if config.until is not None:
        return config.until
    if config.deterministic:
        return max(c.timestamp.date() for c in commits)
    return _today()


def _plural_refs(n: int) -> str:
    """Return "1 replace ref" or "N replace refs"."""
    return f"{n:,} replace ref" if n == 1 else f"{n:,} replace refs"


def _today() -> datetime.date:
    """Return today's date in UTC, the zone every commit timestamp is read in.

    Returns:
        The current UTC calendar date.
    """
    return datetime.datetime.now(datetime.UTC).date()


def _build_provenance(
    config: ReportConfig,
    head_sha: str | None,
    mailmap_applied: bool,
) -> AnalysisProvenance:
    """Record what produced this report, and over what.

    Filters are recorded as requested, not resolved: only `requested_since`
    beside `analysis_since` tells a filtered report from an unfiltered one.

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
        exclude_authors_count=len(config.exclude_authors),
        exclude_paths=tuple(config.exclude_paths),
        min_commits=config.min_commits,
        ranking_enabled=config.ranking_enabled,
        # Reporting weights that were never applied would be a false statement.
        ranking_weights=(config.ranking_weights.model_dump() if config.ranking_enabled else None),
        mailmap_applied=mailmap_applied,
        deterministic=config.deterministic,
    )
