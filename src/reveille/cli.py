# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""CLI entry point for Reveille (`reveille = "reveille.cli:app"`).

Parses flags, builds a ReportConfig and delegates; no business logic.
Exit codes are a contract: see `ExitCode` and docs/USER_GUIDE.md.
"""

from __future__ import annotations

import datetime
import enum
import itertools
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, TextIO, cast

import typer

from reveille import __version__
from reveille.config import OutputFormat, ReportConfig, ReportConfigKwargs
from reveille.domain.models import ProgressEvent
from reveille.domain.repositories import MAX_SEARCH_DEPTH
from reveille.exceptions import ConfigurationError, EmptyRepositoryError, ReveilleError

_logger = logging.getLogger("reveille.cli")


class ExitCode(enum.IntEnum):
    """Process exit codes. Part of Reveille's public CLI contract.

    As with `grep` and `diff`, a negative answer differs from an inability to
    answer. Finer causes go to stderr: new codes would break callers.
    """

    SUCCESS = 0
    """The command ran and its answer is affirmative."""

    NEGATIVE = 1
    """The command ran correctly and its answer is negative.

    Reveille worked as intended and the repository state does not satisfy
    the request: currently, an analysis window containing no commits.
    """

    CANNOT_RUN = 2
    """The command could not run at all.

    Invalid invocation, invalid configuration, a path that is not a
    readable Git repository, or an output location that cannot be written.
    The fault is in the inputs or the environment, not in the answer.
    """


# Terminal control characters, escaped because an untrusted reveille.toml value
# could otherwise erase the warning about it. A table rather than a regex range,
# which CodeQL flags (py/overly-large-range).
_TERMINAL_UNSAFE: dict[int, str] = {
    code: f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"
    for block in (
        range(0x00, 0x09),  # C0 controls before tab
        range(0x0B, 0x20),  # C0 controls after newline, CR and ESC among them
        range(0x7F, 0xA0),  # DEL and the C1 controls
        (0x061C, 0x200E, 0x200F),  # ALM, LRM, RLM: implicit direction marks
        range(0x202A, 0x202F),  # LRE, RLE, PDF, LRO, RLO: embeddings and overrides
        range(0x2066, 0x206A),  # LRI, RLI, FSI, PDI: direction isolates
    )
    for code in block
}


def _printable(text: str) -> str:
    """Show terminal control characters as escapes instead of obeying them.

    Args:
        text: A message that may quote configuration values.

    Returns:
        The message with each unsafe character written as a hexadecimal escape.
    """
    if any("\udc80" <= ch <= "\udcff" for ch in text):
        # A byte Git output held that is not UTF-8 (read with surrogateescape).
        text = text.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
    return text.translate(_TERMINAL_UNSAFE)


#: Whether stderr carries JSON: set when the command was asked for `--format json`,
#: and reset by the root callback for every invocation.
_stderr_json = {"on": False}

_LEVELS = {"Error: ": "error", "Warning: ": "warning", "Note: ": "note"}


def _err(message: str) -> None:
    """Write one message to stderr, with terminal control characters escaped.

    Under `--format json` the message is one JSON object on its own line,
    `{"level": "error" | "warning" | "note" | "message", "message": ...}`.

    Args:
        message: The message to print, starting "Error: ", "Warning: " or "Note: ".
    """
    if _stderr_json["on"]:
        level, text = "message", message
        for prefix, name in _LEVELS.items():
            if message.startswith(prefix):
                level, text = name, message.removeprefix(prefix)
        typer.echo(json.dumps({"level": level, "message": text}), err=True)
        return
    typer.echo(_printable(message), err=True)


_EXCLUDE_PATH_HELP = (
    "Leave a path out of every figure, relative to the repository root and matched "
    "literally; a directory takes everything under it. Repeatable."
)

# Command-line spelling of the configuration fields a user can get wrong.
_OPTION_NAMES = {
    "since": "--since",
    "until": "--until",
    "output_format": "--format",
    "min_commits": "--min-commits",
    "branch": "--branch",
    "title": "--title",
    "output_path": "--output",
    "repo_path": "--repo",
    "exclude_authors": "--exclude-author",
    "exclude_paths": "--exclude-path",
    "area_depth": "--area-depth",
    "limit": "--limit",
}


def _describe_config_error(exc: Exception) -> str:
    """Say what is wrong with a configuration in plain words.

    Keeps only the reason and the option, not Pydantic's dump of every input.

    Args:
        exc: The error raised while building the configuration.

    Returns:
        One sentence per problem, joined with "; ".
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    described = []
    for error in errors():
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        fields = [str(part) for part in error.get("loc", ())]
        option = ", ".join(_option_label(f) for f in fields)
        described.append(f"{option}: {message}" if option else message)
    return "; ".join(described) or str(exc)


def _option_label(field: str) -> str:
    """Name a configuration field as both a flag and a reveille.toml key.

    Args:
        field: A ReportConfig field name.

    Returns:
        For example "--area-depth / areas.depth", or the field unchanged.
    """
    flag = _OPTION_NAMES.get(field)
    key = _TOML_KEYS.get(field)
    if flag and key:
        return f"{flag} / {key}"
    return flag or key or field


class _EscapingFormatter(logging.Formatter):
    """A log formatter that escapes terminal control characters in quoted values."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the record, then escape it.

        Args:
            record: The log record.

        Returns:
            The formatted, escaped line.
        """
        return _printable(super().format(record))


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """A stderr handler that resolves the stream at emit time.

    The handler outlives one invocation, so a stream captured at construction
    could be closed beneath it ("I/O operation on closed file").
    """

    @property
    def stream(self) -> TextIO:
        """The current `sys.stderr`, resolved on every access."""
        return sys.stderr

    @stream.setter
    def stream(self, _value: object) -> None:
        """Ignore assignment; the stream is always the current `sys.stderr`."""

    def emit(self, record: logging.LogRecord) -> None:
        """Write the record, on a line of its own if the progress line is open.

        Args:
            record: The log record.
        """
        if _StageSpinner.line_open:
            _StageSpinner.line_open = False
            self.stream.write("\n")
        if _stderr_json["on"]:
            entry = {"level": record.levelname.lower(), "message": record.getMessage()}
            self.stream.write(json.dumps(entry) + "\n")
            return
        super().emit(record)


def _configure_logging(verbose: bool) -> None:
    """Attach the stderr log handler; `verbose` chooses the level.

    The only place a handler is attached. Always attached, so a warning such as
    an `--exclude-author` matching nobody shows without `--verbose`.

    Args:
        verbose: True to emit DEBUG-level diagnostics as well as warnings.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    package_logger = logging.getLogger("reveille")
    # Idempotent: a second call must not duplicate every diagnostic line.
    if any(isinstance(h, _StderrHandler) for h in package_logger.handlers):
        package_logger.setLevel(level)
        return
    handler = _StderrHandler()
    handler.setFormatter(_EscapingFormatter("%(levelname)s %(name)s: %(message)s"))
    package_logger.addHandler(handler)
    package_logger.setLevel(level)


class _App(typer.Typer):
    """The Typer application, with an exit code for errors nobody anticipated."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Run the CLI; an uncaught exception exits 2 (cannot run), never 1.

        Python exits 1 on an uncaught exception, which the contract reserves for
        a negative answer. The traceback goes to the debug log (`--verbose`).
        """
        try:
            return super().__call__(*args, **kwargs)
        except Exception as exc:
            _logger.debug("Unexpected error", exc_info=True)
            _err(
                f"Error: {type(exc).__name__}: {exc}. This is a defect in Reveille; please report it."
            )
            sys.exit(ExitCode.CANNOT_RUN)


app = _App(
    name="reveille",
    help=(
        "Offline reports and summaries of a local Git repository: HTML, JSON, CSV "
        "and text for scripts, CI and coding agents."
    ),
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# Conventional configuration file, looked up in the working directory.
_CONVENTIONAL_CONFIG: str = "reveille.toml"


def _discover_config() -> Path | None:
    """Return reveille.toml in the working directory, if present.

    Returns:
        Its path, or None.
    """
    candidate = Path(_CONVENTIONAL_CONFIG)
    return candidate if candidate.exists() else None


# Each setting's reveille.toml key, so a notice names it as the user writes it.
_TOML_KEYS: dict[str, str] = {
    "title": "report.title",
    "output_path": "report.output",
    "branch": "report.branch",
    "since": "report.since",
    "until": "report.until",
    "output_format": "report.format",
    "deterministic": "report.deterministic",
    "min_commits": "filters.min_commits",
    "exclude_authors": "filters.exclude_authors",
    "exclude_paths": "filters.exclude_paths",
    "ranking_enabled": "ranking.enabled",
    "ranking_weights": "ranking.weights",
    "area_authors_enabled": "areas.enabled",
    "area_depth": "areas.depth",
    "limit": "report.limit",
    "hide_emails": "report.hide_emails",
}


def _announce_discovered_settings(path: Path, settings: Mapping[str, object]) -> None:
    """Say on stderr that a configuration file was picked up, and what it set.

    An auto-discovered file may come from someone else's repository, so it must
    not change what the report says silently.

    Args:
        path: The configuration file that was loaded.
        settings: The settings it supplied, keyed by `ReportConfig` field.
    """
    keys = ", ".join(_TOML_KEYS.get(name, name) for name in settings)
    _err(f"Loaded settings from {path}: {keys}. Command-line options override them.")


def _print_notices(notices: list[str]) -> None:
    """Print each notice the service raised, on stderr, after the spinner.

    Args:
        notices: Plain sentences, in the order the service raised them.
    """
    for notice in notices:
        _err(f"Note: {notice}")


class _StageSpinner:
    """Per-stage progress indicator on stderr, keeping stdout clean.

    Animates only on a terminal, where carriage returns redraw; elsewhere only
    completion lines are written.
    """

    _FRAMES: ClassVar[list[str]] = [".  ", ".. ", "..."]

    #: True while a frame has been written and its line not yet ended, so a
    #: log line can start a fresh one. Shared because only one spinner runs.
    line_open: ClassVar[bool] = False

    def __init__(self, *, animate: bool | None = None) -> None:
        """Create a spinner.

        Args:
            animate: Whether to animate; None means "if stderr is a terminal".
        """
        self._animate: bool = sys.stderr.isatty() if animate is None else animate
        self._active: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._label: str = ""
        self._elapsed_seconds: float = 0.0
        self._items_processed: int | None = None
        self._start_time: float = 0.0

    def begin(self, label: str) -> None:
        """Start the animated indicator for a new pipeline stage.

        Args:
            label: Human-readable stage name written to stderr.
        """
        self._label = label
        self._elapsed_seconds = 0.0
        self._items_processed = None
        self._start_time = time.monotonic()
        self._stop_event.clear()
        self._active = True
        if not self._animate:
            return
        self._thread = threading.Thread(target=self._run, args=(label,), daemon=True)
        self._thread.start()

    def complete(
        self,
        elapsed_seconds: float | None = None,
        items_processed: int | None = None,
    ) -> None:
        """Stop the animation and write the completion line; no-op if none is running.

        Args:
            elapsed_seconds: Time to display; None measures from begin().
            items_processed: Optional item count for the completion line.
        """
        if not self._active:
            return
        self._elapsed_seconds = (
            elapsed_seconds if elapsed_seconds is not None else time.monotonic() - self._start_time
        )
        self._items_processed = items_processed
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        else:
            self._write_done(self._label)
        self._active = False

    def _run(self, label: str) -> None:
        for frame in itertools.cycle(self._FRAMES):
            sys.stderr.write(f"\r  {label} {frame}")
            sys.stderr.flush()
            _StageSpinner.line_open = True
            if self._stop_event.wait(0.2):
                break
        self._write_done(label, prefix="\r")

    def _write_done(self, label: str, prefix: str = "") -> None:
        elapsed = self._elapsed_seconds
        if self._items_processed is not None:
            count = self._items_processed
            suffix = f"({elapsed:.1f}s, {count:,} commit{'' if count == 1 else 's'})"
        else:
            suffix = f"({elapsed:.1f}s)"
        sys.stderr.write(f"{prefix}  {label} ...   done {suffix}\n")
        sys.stderr.flush()
        _StageSpinner.line_open = False


def _make_progress_callback(spinner: _StageSpinner) -> Callable[[ProgressEvent], None]:
    """Return a progress callback that completes one stage and begins the next.

    Args:
        spinner: The _StageSpinner instance to drive.

    Returns:
        An on_progress callable for generate_report.
    """

    def _callback(event: ProgressEvent) -> None:
        spinner.complete(event.elapsed_seconds, event.items_processed)
        spinner.begin(event.stage)

    return _callback


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"reveille {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Print the installed version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Offline reports of a Git repository's history."""
    _stderr_json["on"] = False


def _root(repo: Path) -> Path:
    """Return the repository `repo` lies in, searching upwards as Git does."""
    from reveille.adapters.git_reader import repository_root

    return repository_root(repo)


def _resolve_output_path(output: Path, repo_path: Path) -> Path:
    """Return the resolved output path; the default is relative to the repository.

    Args:
        output: The output path value received from the CLI flag.
        repo_path: The resolved repository root path.

    Returns:
        The resolved output path.
    """
    if output == Path("reveille-report.html"):
        return repo_path / "reveille-report.html"
    return output


def _git_directories(repo_path: Path) -> list[Path]:
    """Find where the repository keeps Git's own files, in any layout.

    Covers `.git`, a bare repository's top level, `--separate-git-dir`, and a
    linked worktree's `commondir`; matching a `.git` component alone let a
    report overwrite HEAD.

    Args:
        repo_path: The resolved repository root.

    Returns:
        The repository's Git directory, then the common one if different.
    """
    dot_git = repo_path / ".git"
    if dot_git.is_dir():
        git_dir = dot_git.resolve()
    elif dot_git.is_file():
        try:
            pointer = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return []
        if not pointer.startswith("gitdir:"):
            return []
        git_dir = (repo_path / pointer.removeprefix("gitdir:").strip()).resolve()
    elif (repo_path / "HEAD").is_file() and (repo_path / "objects").is_dir():
        git_dir = repo_path.resolve()
    else:
        return []
    directories = [git_dir]
    try:
        common = (git_dir / "commondir").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return directories
    if common:
        common_dir = (git_dir / common).resolve()
        if common_dir != git_dir:
            directories.append(common_dir)
    return directories


def _validate_output_path(output: Path, repo_path: Path, *, from_config: bool = False) -> None:
    """Validate the output path for traversal and the repository boundary.

    Refuses `..`, a Git directory or a directory; warns outside the repository.

    Args:
        output: The output path as given, before resolution.
        repo_path: The resolved repository root.
        from_config: An auto-discovered (untrusted) file supplied the path.

    Raises:
        typer.Exit: ExitCode.CANNOT_RUN if the path is refused.
    """
    # Resolve first, so a symlinked parent is caught; refuse only for a
    # config-supplied path, so `-o /tmp/report.html` still works.
    if from_config:
        resolved = output.expanduser().resolve()
        try:
            inside = resolved.is_relative_to(repo_path)
        except ValueError:  # pragma: no cover - differing drives on Windows
            inside = False
        if not inside:
            _err(
                f"Error: the configuration file sets an output path that resolves "
                f"outside the repository: '{resolved}'.\n"
                "A reveille.toml is discovered automatically from the working "
                "directory, so it may come from a repository you do not control. "
                "Pass --output explicitly if you intended to write here.",
            )
            raise typer.Exit(code=ExitCode.CANNOT_RUN)

    # Writing into a Git directory can corrupt the repository, so it is
    # refused whoever chose the path: flag, config file, or symlink.
    inside_git_dir = any(
        output.resolve().is_relative_to(git_dir) for git_dir in _git_directories(repo_path)
    )
    if inside_git_dir or any(
        part.casefold() == ".git" for part in (*output.parts, *output.resolve().parts)
    ):
        _err(
            f"Error: output path '{output}' is inside the repository's Git "
            "directory. Reveille does not write into Git's own files. "
            "Choose another path.",
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    if output.is_dir():
        _err(
            f"Error: output path '{output}' is a directory. Give a file name, "
            f"for example '{output / 'reveille-report.html'}'."
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    if ".." in output.parts:
        _err(
            f"Error: output path '{output}' contains upward traversal components. "
            "Provide an absolute path or a path relative to the current directory.",
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    if not output.resolve().is_relative_to(repo_path):
        _err(
            f"Warning: output path resolves outside the repository root "
            f"'{repo_path}'. Verify this is intentional.",
        )


def _apply_ranking_flags(
    merged: dict[str, Any],
    *,
    ranking: bool,
    no_ranking: bool,
) -> None:
    """Resolve the two ranking flags against the configuration file.

    Flags win over the file; if both are given, `--no-ranking` wins, as the
    more conservative reading.

    Args:
        merged: The configuration mapping being assembled, modified in place.
        ranking: Whether `--ranking` was passed.
        no_ranking: Whether `--no-ranking` was passed.
    """
    if ranking:
        merged["ranking_enabled"] = True
    if no_ranking:
        merged["ranking_enabled"] = False


def _merge_cli_flags(
    config_kwargs: ReportConfigKwargs,
    repo: Path,
    output: Path,
    since: str | None,
    until: str | None,
    branch: str | None,
    title: str | None,
    exclude_author: list[str] | None,
    min_commits: int | None,
    no_ranking: bool,
    ranking: bool,
    output_format: str | None,
    deterministic: bool,
    area_authors: bool = False,
    area_depth: int | None = None,
    limit: int | None = None,
    exclude_path: list[str] | None = None,
    hide_emails: bool = False,
) -> ReportConfigKwargs:
    """Merge CLI flag values over the configuration file's values.

    A flag left at its default applies only when the file set no value.

    Args:
        config_kwargs: Base kwargs loaded from a TOML file, or empty mapping.
        repo: Resolved repository path from --repo flag.
        output: Output path from --output flag.
        since: Raw since date string, or None if not provided.
        until: Raw until date string, or None if not provided.
        branch: Branch name, or None if not provided.
        title: Report title override, or None if not provided.
        exclude_author: List of authors to exclude, or None.
        min_commits: Minimum commit threshold, or None if not provided.
        no_ranking: Whether ranking is explicitly disabled.
        ranking: Whether ranking is explicitly enabled.
        output_format: Output format, or None if the flag was not given, so the
            file's value is not overwritten by the default.
        deterministic: Whether to produce byte-reproducible output.
        area_authors: Whether --area-authors was given; it only switches on.
        area_depth: Area depth, or None if the flag was not given.
        limit: The most entries per list of people in JSON and CSV, or None.
        exclude_path: Paths to leave out of every figure, or None.
        hide_emails: Whether --hide-emails was given; it only switches on.

    Returns:
        A merged ReportConfigKwargs ready for ReportConfig construction.
    """
    merged: dict[str, Any] = dict(config_kwargs)
    resolved_repo = _root(repo)
    merged["repo_path"] = resolved_repo
    if deterministic:
        merged["deterministic"] = True

    if output != Path("reveille-report.html") or "output_path" not in merged:
        merged["output_path"] = _resolve_output_path(output, resolved_repo)
    if since is not None:
        merged["since"] = _parse_date(since, "--since")
    if until is not None:
        merged["until"] = _parse_date(until, "--until")
    if branch is not None:
        merged["branch"] = branch
    if title is not None:
        merged["title"] = title
    if exclude_author:
        merged["exclude_authors"] = exclude_author
    merged.update({"exclude_paths": exclude_path} if exclude_path else {})
    merged.update({"hide_emails": True} if hide_emails else {})
    if min_commits is not None:
        merged["min_commits"] = min_commits
    _apply_ranking_flags(merged, ranking=ranking, no_ranking=no_ranking)
    _apply_area_flags(merged, area_authors=area_authors, area_depth=area_depth)
    merged.update({"limit": limit} if limit is not None else {})
    if output_format is not None:
        merged["output_format"] = cast(OutputFormat, output_format)

    return cast(ReportConfigKwargs, merged)


def _run_report(report_config: ReportConfig, *, to_stdout: bool, quiet: bool = False) -> None:
    """Run the pipeline with a progress indicator, then print the outcome.

    Args:
        report_config: The validated configuration.
        to_stdout: Whether the report goes to stdout (`--output -`).
        quiet: Omit progress lines; notes, warnings and errors still print.

    Raises:
        typer.Exit: NEGATIVE for an empty window, CANNOT_RUN otherwise.
    """
    from reveille.services.report import generate_report, report_text

    spinner = _StageSpinner()
    # Held until the spinner finishes, so no frame overwrites a notice.
    notices: list[str] = []
    progress = None if quiet else _make_progress_callback(spinner)
    try:
        if to_stdout:
            text = report_text(report_config, on_progress=progress, on_notice=notices.append)
        else:
            written = generate_report(report_config, on_progress=progress, on_notice=notices.append)
    except EmptyRepositoryError as exc:
        spinner.complete()
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.NEGATIVE) from exc
    except ReveilleError as exc:
        spinner.complete()
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    spinner.complete()
    _print_notices(notices)
    if to_stdout:
        typer.echo(text, nl=not text.endswith("\n"))
        return
    for path in written:
        typer.echo(_printable(f"Report written to: {path}"))


def _apply_area_flags(
    merged: dict[str, Any], *, area_authors: bool, area_depth: int | None
) -> None:
    """Apply --area-authors and --area-depth over the configuration file.

    Args:
        merged: The configuration being assembled; mutated in place.
        area_authors: Whether --area-authors was given.
        area_depth: The --area-depth value, or None if it was not given.
    """
    if area_authors:
        merged["area_authors_enabled"] = True
    if area_depth is not None:
        merged["area_depth"] = area_depth
        if not merged.get("area_authors_enabled"):
            _err("Note: --area-depth has no effect without --area-authors.")


@app.command()
def generate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="The Git repository, or any directory inside it."),
    ] = Path("."),
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output path for the HTML report."),
    ] = Path("reveille-report.html"),
    since: Annotated[
        str | None,
        typer.Option("--since", help="Include commits on or after this date (YYYY-MM-DD)."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Include commits on or before this date (YYYY-MM-DD)."),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option("--branch", "-b", help="Analyse commits reachable from this branch only."),
    ] = None,
    exclude_author: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-author",
            help="Exclude a contributor by name or email. Repeatable.",
        ),
    ] = None,
    exclude_path: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-path",
            help=_EXCLUDE_PATH_HELP,
        ),
    ] = None,
    min_commits: Annotated[
        int | None,
        typer.Option(
            "--min-commits",
            help=(
                "List only contributors with at least this many commits. "
                "Totals and charts still count everyone."
            ),
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Override the report title in the HTML output."),
    ] = None,
    ranking: Annotated[
        bool,
        typer.Option(
            "--ranking",
            help=(
                "Include the contributor ranking table. Off by default: it "
                "scores and tiers named individuals, which is not what the "
                "figures support."
            ),
        ),
    ] = False,
    no_ranking: Annotated[
        bool,
        typer.Option(
            "--no-ranking",
            help="Omit the ranking even if the configuration file enables it.",
        ),
    ] = False,
    output_format: Annotated[
        str | None,
        typer.Option(
            "--format",
            help="Output format. Accepted values: html, json, csv. [default: html]",
        ),
    ] = None,
    hide_emails: Annotated[
        bool,
        typer.Option(
            "--hide-emails",
            help=(
                "Replace people's email addresses with per-report tokens, for a report "
                "you share. Names, file paths and the licence notices of the bundled chart "
                "library stay; every figure is unchanged."
            ),
        ),
    ] = False,
    deterministic: Annotated[
        bool,
        typer.Option(
            "--deterministic",
            help=(
                "Produce byte-identical output on the same version, dependencies "
                "and Git settings. Pins the timestamp to the analysed commit "
                "and closes the window on the last commit rather than today."
            ),
        ),
    ] = False,
    area_authors: Annotated[
        bool,
        typer.Option(
            "--area-authors",
            help=(
                "Add a section naming who changed each of the most-changed "
                "directories. Off by default: it names people by area."
            ),
        ),
    ] = False,
    area_depth: Annotated[
        int | None,
        typer.Option(
            "--area-depth",
            help="Directory components that make an area (default 3).",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            help=(
                "Bound every list of people in JSON and CSV to this many, with "
                "the full total beside it; the HTML report is not bounded. Default: every one."
            ),
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to a TOML configuration file."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Emit diagnostic logging to stderr. Does not change normal output.",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Do not show progress. Notes, warnings and errors are still shown.",
        ),
    ] = False,
) -> None:
    """Generate an HTML activity report for the target repository."""
    from reveille.config import load_config_from_toml

    _configure_logging(verbose)

    config_kwargs: ReportConfigKwargs = cast(ReportConfigKwargs, {})
    _auto_discovered = config is None
    _config_path = config if config is not None else _discover_config()
    if _config_path is not None:
        try:
            config_kwargs = load_config_from_toml(_config_path)
        except ConfigurationError as exc:
            if _auto_discovered:
                _err(
                    f"Configuration error in the auto-discovered "
                    f"{_CONVENTIONAL_CONFIG}.\nDetail: {_describe_config_error(exc)}\n"
                    f"Correct the file, or regenerate it with: "
                    f"reveille init --force",
                )
            else:
                _err(f"Configuration error: {_describe_config_error(exc)}")
            raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
        if _auto_discovered and config_kwargs:
            _announce_discovered_settings(_config_path, config_kwargs)

    merged = _merge_cli_flags(
        config_kwargs,
        repo,
        output,
        since,
        until,
        branch,
        title,
        exclude_author,
        min_commits,
        no_ranking,
        ranking,
        output_format,
        deterministic,
        area_authors,
        area_depth,
        limit,
        exclude_path,
        hide_emails,
    )

    # Validate the effective path, which a reveille.toml may have supplied.
    # Only an auto-discovered config is untrusted; `--config` is typed, like
    # `--output`, so it gets a warning rather than a refusal.
    _output_from_config = (
        _auto_discovered
        and "output_path" in config_kwargs
        and output == Path("reveille-report.html")
    )
    # `--output -` writes only the report to stdout (ADR 0015); no path to check.
    to_stdout = str(merged.get("output_path", output)) == "-"
    if not to_stdout:
        _validate_output_path(
            Path(merged.get("output_path", output)),
            merged["repo_path"],
            from_config=_output_from_config,
        )

    try:
        report_config = ReportConfig(**merged)
    except ValueError as exc:
        _err(f"Configuration error: {_describe_config_error(exc)}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    _logger.debug(
        "resolved configuration: repo=%s output=%s branch=%s since=%s until=%s "
        "min_commits=%s exclude_authors_count=%s ranking_enabled=%s format=%s",
        report_config.repo_path,
        report_config.output_path,
        report_config.branch,
        report_config.since,
        report_config.until,
        report_config.min_commits,
        # How many, not who: the log is pasted into CI output (ADR 0021).
        len(report_config.exclude_authors),
        report_config.ranking_enabled,
        report_config.output_format,
    )

    _run_report(report_config, to_stdout=to_stdout, quiet=quiet)


def _query_config(
    repo: Path,
    since: str | None,
    until: str | None,
    branch: str | None,
    exclude_author: list[str] | None,
    deterministic: bool,
    exclude_path: list[str] | None = None,
) -> ReportConfig:
    """Build the configuration for `summary`, `brief` and `who-changed` from options.

    No reveille.toml is read, so the answer depends only on the options passed.

    Raises:
        typer.Exit: CANNOT_RUN if an option is invalid.
    """
    kwargs: dict[str, Any] = {"repo_path": _root(repo), "deterministic": deterministic}
    if since is not None:
        kwargs["since"] = _parse_date(since, "--since")
    if until is not None:
        kwargs["until"] = _parse_date(until, "--until")
    if branch is not None:
        kwargs["branch"] = branch
    if exclude_author:
        kwargs["exclude_authors"] = exclude_author
    if exclude_path:
        kwargs["exclude_paths"] = exclude_path
    try:
        return ReportConfig(**kwargs)
    except ValueError as exc:
        _err(f"Configuration error: {_describe_config_error(exc)}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc


def _run_query(produce: Callable[[Callable[[str], None]], str]) -> None:
    """Run a query command and print its answer, and only its answer, on stdout.

    Args:
        produce: Called with a notice sink; returns the text to print.

    Raises:
        typer.Exit: NEGATIVE for an empty answer, CANNOT_RUN otherwise.
    """
    notices: list[str] = []
    try:
        text = produce(notices.append)
    except EmptyRepositoryError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.NEGATIVE) from exc
    except ReveilleError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    _print_notices(notices)
    # The text carries repository-chosen names, so it is escaped like
    # stderr; json.dumps already escapes control characters.
    text = _printable(text)
    typer.echo(text, nl=not text.endswith("\n"))


def _check_query_format(output_format: str, allowed: tuple[str, ...] = ("text", "json")) -> None:
    """Refuse a --format the command does not offer; under json, stderr is JSON too."""
    _stderr_json["on"] = output_format == "json"
    if output_format not in allowed:
        choices = ", ".join(allowed[:-1]) + f" or {allowed[-1]}"
        _err(f"Error: --format must be {choices}, not {output_format!r}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)


_RepoOption = Annotated[
    Path, typer.Option("--repo", "-r", help="The Git repository, or any directory inside it.")
]
_SinceOption = Annotated[
    str | None, typer.Option("--since", help="Include commits on or after this date (YYYY-MM-DD).")
]
_UntilOption = Annotated[
    str | None, typer.Option("--until", help="Include commits on or before this date (YYYY-MM-DD).")
]
_BranchOption = Annotated[
    str | None, typer.Option("--branch", "-b", help="Analyse commits reachable from this branch.")
]
_ExcludeOption = Annotated[
    list[str] | None,
    typer.Option("--exclude-author", help="Exclude a contributor by name or email. Repeatable."),
]
_ExcludePathOption = Annotated[
    list[str] | None, typer.Option("--exclude-path", help=_EXCLUDE_PATH_HELP)
]
_DeterministicOption = Annotated[
    bool,
    typer.Option("--deterministic", help="Close the window on the last commit, not today."),
]
_QueryFormatOption = Annotated[str, typer.Option("--format", help="Output format: text or json.")]
_ShareFormatOption = Annotated[
    str, typer.Option("--format", help="Output format: text, json or markdown.")
]
_StatusFormatOption = Annotated[
    str, typer.Option("--format", help="Output format: text, json, markdown or line.")
]
_VerboseOption = Annotated[
    bool, typer.Option("--verbose", help="Emit diagnostic logging to stderr.")
]


@app.command()
def summary(
    repo: _RepoOption = Path("."),
    since: _SinceOption = None,
    until: _UntilOption = None,
    branch: _BranchOption = None,
    exclude_author: _ExcludeOption = None,
    exclude_path: _ExcludePathOption = None,
    deterministic: _DeterministicOption = False,
    output_format: _ShareFormatOption = "text",
    verbose: _VerboseOption = False,
) -> None:
    """Summarise the repository in a few lines, naming no contributor.

    Small counts can identify someone.
    """
    from reveille.services.report import summary_text

    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown"))
    config = _query_config(repo, since, until, branch, exclude_author, deterministic, exclude_path)
    _run_query(lambda notice: summary_text(config, output_format, on_notice=notice))


@app.command()
def brief(
    repo: _RepoOption = Path("."),
    from_revision: Annotated[
        str | None,
        typer.Option(
            "--from",
            help="A tag, branch or commit; count what came after it on the branch.",
        ),
    ] = None,
    since: _SinceOption = None,
    until: _UntilOption = None,
    branch: _BranchOption = None,
    exclude_author: _ExcludeOption = None,
    exclude_path: _ExcludePathOption = None,
    deterministic: _DeterministicOption = False,
    output_format: _StatusFormatOption = "text",
    limit: Annotated[
        int, typer.Option("--limit", min=1, help="The most entries any list shows.")
    ] = 5,
    verbose: _VerboseOption = False,
) -> None:
    """Say what changed since a tag, a commit or a date, in counts naming no one.

    Small counts can identify someone.
    """
    from reveille.services.report import brief_text

    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown", "line"))
    if from_revision is not None and since is not None:
        _err("Error: give --from <revision> or --since <date>, not both.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    config = _query_config(repo, since, until, branch, exclude_author, deterministic, exclude_path)
    _run_query(
        lambda notice: brief_text(config, from_revision, output_format, limit, on_notice=notice)
    )


@app.command()
def state(
    repo: _RepoOption = Path("."),
    output_format: _StatusFormatOption = "text",
    limit: Annotated[
        int, typer.Option("--limit", min=1, help="The most paths any list shows.")
    ] = 10,
    verbose: _VerboseOption = False,
) -> None:
    """Say where the repository stands now: branch, work in progress, changes, worktrees.

    Names no author, but lists local paths (changed files and worktree
    directories, which can contain your login name), the current branch, its
    upstream and the branches checked out in worktrees.
    """
    from reveille.services.report import state_text

    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown", "line"))
    _run_query(lambda _notice: state_text(_root(repo), output_format, limit))


@app.command()
def repos(
    directory: Annotated[
        Path,
        typer.Argument(help="The directory holding the repositories."),
    ] = Path("."),
    depth: Annotated[
        int,
        typer.Option(
            "--depth",
            min=1,
            max=MAX_SEARCH_DEPTH,
            help="How many directory levels below it to search for repositories.",
        ),
    ] = 1,
    days: Annotated[
        int,
        typer.Option(
            "--days",
            min=1,
            max=3650,
            help="The activity window, in days, ending on --until.",
        ),
    ] = 90,
    until: _UntilOption = None,
    exclude_author: _ExcludeOption = None,
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text, json, markdown or csv.")
    ] = "text",
    verbose: _VerboseOption = False,
) -> None:
    """Say which repositories in a directory are active, quiet or dormant, naming no one.

    One row per repository, in counts. Nobody is counted across repositories.
    """
    from reveille.services.report import repositories_text

    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown", "csv"))
    if not directory.is_dir():
        _err(f"Error: '{directory}' is not a directory.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    end = _parse_date(until, "--until") if until is not None else None
    _run_query(
        lambda notice: repositories_text(
            directory.resolve(),
            depth=depth,
            days=days,
            until=end,
            exclude_authors=list(exclude_author or []),
            output_format=output_format,
            on_notice=notice,
        )
    )


def _repository_path(path: str, repo: Path) -> str:
    """Turn the path given to who-changed into a repository-relative one.

    Args:
        path: As typed: absolute, or relative to the working directory when that
            is inside the repository, else to the repository root.
        repo: The repository root, resolved.

    Returns:
        A repository-relative path with forward slashes ("." for the root).

    Raises:
        typer.Exit: CANNOT_RUN for a path outside the repository.
    """
    if not path.strip():
        _err("Error: give a path inside the repository; use '.' for all of it.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    candidate = Path(path)
    here = Path.cwd().resolve()
    if not candidate.is_absolute() and here.is_relative_to(repo) and here != repo:
        # Inside the repository, a relative path is relative to where it runs, as in Git.
        candidate = Path(os.path.normpath(here / candidate))
    if candidate.is_absolute():
        try:
            # Resolve the directory, not the final name: a symlink has its own history.
            candidate = (candidate.parent.resolve() / candidate.name).relative_to(repo)
        except ValueError as exc:
            _err(f"Error: '{path}' is outside the repository '{repo}'.")
            raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    if ".." in candidate.parts:
        _err(f"Error: '{path}' climbs out of the repository; give a path inside it.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    return candidate.as_posix()


@app.command(name="who-changed")
def who_changed(
    path: Annotated[
        str,
        typer.Argument(
            help="A file or directory: relative to the current directory inside the "
            "repository, else to its root."
        ),
    ],
    repo: _RepoOption = Path("."),
    since: _SinceOption = None,
    until: _UntilOption = None,
    branch: _BranchOption = None,
    exclude_author: _ExcludeOption = None,
    deterministic: _DeterministicOption = False,
    output_format: _QueryFormatOption = "text",
    limit: Annotated[
        int, typer.Option("--limit", min=1, help="The most names any list shows.")
    ] = 20,
    verbose: _VerboseOption = False,
) -> None:
    """Say who changed a file or directory, and who changed it most recently."""
    from reveille.services.report import who_changed_text

    _configure_logging(verbose)
    _check_query_format(output_format)
    relative = _repository_path(path, _root(repo))
    config = _query_config(repo, since, until, branch, exclude_author, deterministic)
    _run_query(
        lambda notice: who_changed_text(config, relative, output_format, limit, on_notice=notice)
    )


@app.command()
def validate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="The Git repository, or any directory inside it."),
    ] = Path("."),
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Emit diagnostic logging to stderr. Does not change normal output.",
        ),
    ] = False,
) -> None:
    """Validate that the target path is a readable Git repository with at least one commit."""
    from reveille.adapters.git_reader import GitReader

    _configure_logging(verbose)
    resolved = _root(repo)
    try:
        reader = GitReader(resolved)
    except ReveilleError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    try:
        reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
    except EmptyRepositoryError:
        _err(f"Error: repository at '{resolved}' contains no commits.")
        raise typer.Exit(code=ExitCode.NEGATIVE) from None
    except ReveilleError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    typer.echo(_printable(f"Repository at {resolved} is valid."))


@app.command()
def init(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Destination path for the generated configuration file.",
        ),
    ] = Path("reveille.toml"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace an existing file.",
        ),
    ] = False,
    mailmap: Annotated[
        bool,
        typer.Option(
            "--mailmap",
            help="Generate an annotated .mailmap template alongside reveille.toml.",
        ),
    ] = False,
) -> None:
    """Scaffold an annotated reveille.toml configuration file.

    Writes a configuration file to the current directory (or the path given
    by --output) with every key present and commented out, showing its
    default. Uncomment and edit only the keys you want to override. Pass
    --mailmap to also generate an annotated .mailmap template at the
    repository root.
    """
    cwd = Path(".").resolve()
    if not (cwd / ".git").exists():
        _err(
            f"Error: '{cwd}' is not a Git repository root. "
            "Run reveille init from within a repository root.",
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    _validate_output_path(output, cwd)

    from reveille.init import write_init_config, write_mailmap_template

    try:
        written_path = write_init_config(output, force=force)
        typer.echo(f"Configuration file written to: {written_path}")
    except ReveilleError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    if mailmap:
        try:
            mailmap_result = write_mailmap_template(cwd / ".mailmap", force=force)
        except ReveilleError as exc:
            _err(f"Error: {exc}")
            raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
        if mailmap_result is not None:
            typer.echo(f".mailmap template written to: {mailmap_result}")
        else:
            typer.echo(".mailmap already exists; skipped.")


@app.command()
def capabilities(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format. Accepted values: text, json.",
        ),
    ] = "text",
    command: Annotated[
        str | None,
        typer.Option("--command", help="Describe only this command, its options and exit codes."),
    ] = None,
) -> None:
    """Describe what Reveille can and cannot do, for a person or a program."""
    from reveille.capabilities import (
        build_capabilities,
        command_capabilities,
        render_command_text,
        render_text,
    )

    _stderr_json["on"] = output_format == "json"
    if output_format not in {"text", "json"}:
        _err(f"Error: unsupported format '{output_format}'. Accepted values: text, json.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    document = build_capabilities(app, ExitCode)
    if command is not None:
        narrowed = command_capabilities(document, command)
        if narrowed is None:
            known = ", ".join(c["name"] for c in document["commands"])
            _err(f"Error: no command {command!r}; the commands are {known}.")
            raise typer.Exit(code=ExitCode.CANNOT_RUN)
        typer.echo(
            json.dumps(narrowed, indent=2)
            if output_format == "json"
            else render_command_text(narrowed)
        )
        return
    if output_format == "json":
        typer.echo(json.dumps(document, indent=2))
    else:
        typer.echo(render_text(document))


@app.command()
def skill(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="markdown: a section for AGENTS.md or CLAUDE.md; skill: a SKILL.md.",
        ),
    ] = "markdown",
) -> None:
    """Print what to tell a coding agent about Reveille, for its instructions file.

    Reads no repository.
    """
    from reveille.agent_guide import guide

    if output_format not in {"markdown", "skill"}:
        _err(f"Error: unsupported format '{output_format}'. Accepted values: markdown, skill.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    typer.echo(guide(output_format), nl=False)


@app.command()
def help(ctx: typer.Context) -> None:
    """Display help information for all available commands."""
    if ctx.parent is not None:
        typer.echo(ctx.parent.get_help())
    else:
        typer.echo(ctx.get_help())


def _parse_date(value: str, flag_name: str) -> datetime.date:
    """Parse a YYYY-MM-DD string into a date object.

    Args:
        value: The string value to parse.
        flag_name: The CLI flag name, used in the error message.

    Returns:
        A datetime.date instance.

    Raises:
        typer.Exit: ExitCode.CANNOT_RUN if the format is invalid.
    """
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as exc:
        _err(f"Error: {flag_name} must be in YYYY-MM-DD format, got '{value}'.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    if parsed == datetime.date.max:
        # An inclusive end is read up to the next day, which does not exist.
        _err(f"Error: {flag_name} must be before {value}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    return parsed
