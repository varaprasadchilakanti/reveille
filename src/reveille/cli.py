# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""CLI entry point for Reveille.

Defines the public commands: generate, validate, init, version, help.
Responsible for flag parsing, boundary validation, constructing
a ReportConfig, and delegating to the application service.
Contains no business logic.

Entry point registered in pyproject.toml:
    reveille = "reveille.cli:app"

Exit codes are a supported contract — see `ExitCode` below and the
"Exit Codes" section of docs/USER_GUIDE.md.
"""

from __future__ import annotations

import datetime
import enum
import itertools
import json
import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, ClassVar, TextIO, cast

import typer

from reveille import __version__
from reveille.config import OutputFormat, ReportConfig, ReportConfigKwargs
from reveille.domain.models import ProgressEvent
from reveille.exceptions import ConfigurationError, EmptyRepositoryError, ReveilleError

_logger = logging.getLogger("reveille.cli")


class ExitCode(enum.IntEnum):
    """Process exit codes. Part of Reveille's public CLI contract.

    The split follows the convention used by `grep` and `diff`, where the
    code distinguishes *a negative answer* from *an inability to answer*.
    That distinction is the one a CI job acts on: a negative answer may be
    an acceptable state to record, whereas an inability to answer is a
    broken pipeline step.

    Diagnostic detail beyond this three-way split belongs in the stderr
    message, not in the exit code. Encoding individual causes as distinct
    codes does not scale — the range is small, and every new cause becomes
    a breaking change for anyone branching on the old numbering.
    """

    SUCCESS = 0
    """The command ran and its answer is affirmative."""

    NEGATIVE = 1
    """The command ran correctly and its answer is negative.

    Reveille worked as intended and the repository state does not satisfy
    the request — currently, an analysis window containing no commits.
    """

    CANNOT_RUN = 2
    """The command could not run at all.

    Invalid invocation, invalid configuration, a path that is not a
    readable Git repository, or an output location that cannot be written.
    The fault is in the inputs or the environment, not in the answer.
    """


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """A stderr handler that resolves the stream at emit time.

    `logging.StreamHandler` captures `sys.stderr` when it is constructed. A
    handler now outlives a single invocation -- it is attached on every run, not
    only under `--verbose` -- so a captured stream can be closed or replaced
    beneath it, which raises `ValueError: I/O operation on closed file` from
    inside the logging machinery. Looking the stream up on each write costs an
    attribute access and removes the failure mode.
    """

    @property
    def stream(self) -> TextIO:
        """The current `sys.stderr`, resolved on every access."""
        return sys.stderr

    @stream.setter
    def stream(self, _value: object) -> None:
        """Ignore assignment; the stream is always the current `sys.stderr`."""


def _configure_logging(verbose: bool) -> None:
    """Attach a stderr log handler when diagnostics are requested.

    Reveille's library modules log through the standard `logging` module
    and never install a handler of their own, per the convention for
    libraries. This is the only place a handler is attached, so importing
    Reveille as a library stays silent unless the host application opts in.

    A handler is always attached; `verbose` chooses the level. Warnings are
    not diagnostics -- `--exclude-author` matching nobody is the case this
    matters for, and it was previously visible only with `--verbose`, so a
    filter that silently did nothing looked exactly like one that worked. That
    is the wrong thing to hide for the one flag whose purpose is privacy.

    Args:
        verbose: True to emit DEBUG-level diagnostics as well as warnings.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    package_logger = logging.getLogger("reveille")
    # Idempotent: a second call in the same process must not duplicate
    # every diagnostic line. Only the NullHandler installed at import
    # time is expected to be present here.
    if any(isinstance(h, _StderrHandler) for h in package_logger.handlers):
        package_logger.setLevel(level)
        return
    handler = _StderrHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    package_logger.addHandler(handler)
    package_logger.setLevel(level)


app = typer.Typer(
    name="reveille",
    help="Generate self-contained HTML performance reports from local Git repositories.",
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# Conventional configuration file name. Resolved against the current
# working directory at invocation time. Users are not required to pass
# --config when this file is present at the repository root.
_CONVENTIONAL_CONFIG: str = "reveille.toml"


def _discover_config() -> Path | None:
    """Return the path to the conventional configuration file if present.

    Looks for reveille.toml in the current working directory. This
    implements the convention-over-configuration lookup: users who run
    reveille generate from their repository root do not need to pass
    --config explicitly when the canonical file name is used.

    Returns:
        The Path to reveille.toml if it exists in the current directory,
        or None if no conventional configuration file is present.
    """
    candidate = Path(_CONVENTIONAL_CONFIG)
    return candidate if candidate.exists() else None


class _StageSpinner:
    """Per-stage progress indicator for the generate pipeline.

    Writes animated stage labels to stderr. Each stage begins with
    begin() and resolves to a static completion line on complete().
    Writes to stderr so stdout remains clean for scripting.

    complete() is safe to call before begin() has ever been invoked.
    """

    _FRAMES: ClassVar[list[str]] = [".  ", ".. ", "..."]

    def __init__(self) -> None:
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
        self._thread = threading.Thread(target=self._run, args=(label,), daemon=True)
        self._thread.start()

    def complete(
        self,
        elapsed_seconds: float | None = None,
        items_processed: int | None = None,
    ) -> None:
        """Stop the current animation and write the completion line.

        No-op if begin() has not been called or if already completed.

        Args:
            elapsed_seconds: Elapsed time to display. When None, computed
                from the spinner's own start time.
            items_processed: Optional item count appended to the completion
                line (e.g. commit count from the reading stage).
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
        self._active = False

    def _run(self, label: str) -> None:
        for frame in itertools.cycle(self._FRAMES):
            sys.stderr.write(f"\r  {label} {frame}")
            sys.stderr.flush()
            if self._stop_event.wait(0.2):
                break
        elapsed = self._elapsed_seconds
        if self._items_processed is not None:
            suffix = f"({elapsed:.1f}s, {self._items_processed:,} commits)"
        else:
            suffix = f"({elapsed:.1f}s)"
        sys.stderr.write(f"\r  {label} ...   done {suffix}\n")
        sys.stderr.flush()


def _make_progress_callback(spinner: _StageSpinner) -> Callable[[ProgressEvent], None]:
    """Return a progress callback that drives the given spinner.

    On each invocation, completes the previous stage animation with timing
    from the event and starts a new one for the incoming stage label.

    Args:
        spinner: The _StageSpinner instance to drive.

    Returns:
        A callable suitable for passing as on_progress to generate_report.
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
    """Reveille -- Git Repository Intelligence."""


def _resolve_output_path(output: Path, repo_path: Path) -> Path:
    """Return the resolved output path for the generated report.

    When the output argument is still at its CLI default value, the report
    is placed at the repository root rather than the current working directory.
    This matches the documented behaviour: the default output path is
    relative to the repository, not the shell's working directory.

    Args:
        output: The output path value received from the CLI flag.
        repo_path: The resolved repository root path.

    Returns:
        The resolved output path.
    """
    if output == Path("reveille-report.html"):
        return repo_path / "reveille-report.html"
    return output


def _validate_output_path(output: Path, repo_path: Path, *, from_config: bool = False) -> None:
    """Validate the output path for traversal components and boundary awareness.

    Rejects paths containing upward traversal components before resolution.
    Emits a stderr warning when the resolved output path falls outside the
    repository root, making cross-boundary writes auditable in CI without
    restricting legitimate use.

    Args:
        output: The output path as provided by the user (pre-resolution).
        repo_path: The resolved repository root used as the boundary reference.
        from_config: Whether the path came from a configuration file rather
            than from an explicit `--output` flag. A path the user typed may
            legitimately point anywhere; a path a *file* supplied may not,
            because `reveille.toml` is auto-discovered from the working
            directory and can therefore arrive inside a repository somebody
            else controls.

    Raises:
        typer.Exit: ExitCode.CANNOT_RUN if the path contains upward
            traversal components.
    """
    # A symlinked *parent* directory is not a symlink at the leaf, so checking
    # only the final component misses it. Resolving first and then comparing
    # against the repository root catches the whole chain -- and refusing only
    # for a config-supplied path keeps `-o /tmp/report.html` working, which is
    # ordinary use.
    if from_config:
        resolved = output.expanduser().resolve()
        try:
            inside = resolved.is_relative_to(repo_path)
        except ValueError:  # pragma: no cover - differing drives on Windows
            inside = False
        if not inside:
            typer.echo(
                f"Error: the configuration file sets an output path that resolves "
                f"outside the repository: '{resolved}'.\n"
                "A reveille.toml is discovered automatically from the working "
                "directory, so it may come from a repository you do not control. "
                "Pass --output explicitly if you intended to write here.",
                err=True,
            )
            raise typer.Exit(code=ExitCode.CANNOT_RUN)

    if ".." in output.parts:
        typer.echo(
            f"Error: output path '{output}' contains upward traversal components. "
            "Provide an absolute path or a path relative to the current directory.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    if not output.resolve().is_relative_to(repo_path):
        typer.echo(
            f"Warning: output path resolves outside the repository root "
            f"'{repo_path}'. Verify this is intentional.",
            err=True,
        )


def _apply_ranking_flags(
    merged: dict[str, Any],
    *,
    ranking: bool,
    no_ranking: bool,
) -> None:
    """Resolve the two ranking flags against the configuration file.

    Explicit flags win over the file. If both are given, `--no-ranking` wins:
    between two contradictory instructions, the one that produces less is the
    safer reading, and the ranking is the part of the output that most needs a
    deliberate decision behind it.

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
) -> ReportConfigKwargs:
    """Merge CLI flag values into the base configuration dict.

    CLI flag values always take precedence over configuration file values.
    Flags that were not explicitly set by the user (i.e. still at their
    default) are only applied when no configuration file provided a value.

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
        output_format: Output format string, or None if the flag was not given.
            A `None` sentinel rather than the default value, because comparing
            against "html" cannot tell an explicit `--format html` from an
            absent flag -- and an unconditional assignment here silently
            overwrote whatever `reveille.toml` had set.
        deterministic: Whether to produce byte-reproducible output.

    Returns:
        A merged ReportConfigKwargs ready for ReportConfig construction.
    """
    merged: dict[str, Any] = dict(config_kwargs)
    resolved_repo = repo.resolve()
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
    if min_commits is not None:
        merged["min_commits"] = min_commits
    _apply_ranking_flags(merged, ranking=ranking, no_ranking=no_ranking)
    if output_format is not None:
        merged["output_format"] = cast(OutputFormat, output_format)

    return cast(ReportConfigKwargs, merged)


@app.command()
def generate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the Git repository root."),
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
    min_commits: Annotated[
        int | None,
        typer.Option("--min-commits", help="Exclude contributors below this commit threshold."),
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
            help="Explicitly omit the ranking table. Ranking is already off by default.",
        ),
    ] = False,
    output_format: Annotated[
        str | None,
        typer.Option(
            "--format",
            help="Output format. Accepted values: html, json, csv. [default: html]",
        ),
    ] = None,
    deterministic: Annotated[
        bool,
        typer.Option(
            "--deterministic",
            help=(
                "Produce byte-reproducible output. Pins the timestamp and the "
                "analysis window to the repository rather than to the clock."
            ),
        ),
    ] = False,
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
) -> None:
    """Generate an HTML performance report for the target repository."""
    from reveille.config import load_config_from_toml
    from reveille.services.report import generate_report

    _configure_logging(verbose)

    config_kwargs: ReportConfigKwargs = cast(ReportConfigKwargs, {})
    _auto_discovered = config is None
    _config_path = config if config is not None else _discover_config()
    if _config_path is not None:
        try:
            config_kwargs = load_config_from_toml(_config_path)
        except ConfigurationError as exc:
            if _auto_discovered:
                typer.echo(
                    f"Configuration error in the auto-discovered "
                    f"{_CONVENTIONAL_CONFIG}.\nDetail: {exc}\n"
                    f"Correct the file, or regenerate it with: "
                    f"reveille init --force",
                    err=True,
                )
            else:
                typer.echo(f"Configuration error: {exc}", err=True)
            raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

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
    )

    # Validate the EFFECTIVE path, not the flag. `merged["output_path"]` may
    # have come from a reveille.toml -- including one auto-discovered inside a
    # repository somebody else controls -- and validating the CLI argument left
    # that path unchecked, so a config file could write outside the repository
    # with no traversal warning at all.
    # Only an AUTO-DISCOVERED config is untrusted. `--config /path/to.toml` is a
    # path the user typed, exactly like `--output`, so it earns the same
    # latitude: a warning rather than a refusal. Treating both alike blocked a
    # deliberate choice and told the user their file had been "discovered
    # automatically", which was not true.
    _output_from_config = (
        _auto_discovered
        and "output_path" in config_kwargs
        and output == Path("reveille-report.html")
    )
    _validate_output_path(
        Path(merged.get("output_path", output)),
        repo.resolve(),
        from_config=_output_from_config,
    )

    try:
        report_config = ReportConfig(**merged)
    except ValueError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    _logger.debug(
        "resolved configuration: repo=%s output=%s branch=%s since=%s until=%s "
        "min_commits=%s exclude_authors=%s ranking_enabled=%s format=%s",
        report_config.repo_path,
        report_config.output_path,
        report_config.branch,
        report_config.since,
        report_config.until,
        report_config.min_commits,
        report_config.exclude_authors,
        report_config.ranking_enabled,
        report_config.output_format,
    )

    spinner = _StageSpinner()
    try:
        written_paths = generate_report(
            report_config,
            on_progress=_make_progress_callback(spinner),
        )
    except EmptyRepositoryError as exc:
        spinner.complete()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=ExitCode.NEGATIVE) from exc
    except ReveilleError as exc:
        spinner.complete()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    else:
        spinner.complete()
        for path in written_paths:
            typer.echo(f"Report written to: {path}")


@app.command()
def validate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the Git repository root."),
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
    resolved = repo.resolve()
    try:
        reader = GitReader(resolved)
    except ReveilleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    try:
        reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
    except EmptyRepositoryError:
        typer.echo(
            f"Error: repository at '{resolved}' contains no commits.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.NEGATIVE) from None
    except ReveilleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    typer.echo(f"Repository at {resolved} is valid.")


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
            help="Overwrite an existing configuration file without prompting.",
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

    Writes a fully commented configuration file to the current directory
    (or the path specified by --output) with all keys present and set to
    their defaults. Uncomment and edit only the keys you want to override.
    Pass --mailmap to also generate an annotated .mailmap template at the
    repository root.
    """
    cwd = Path(".").resolve()
    if not (cwd / ".git").exists():
        typer.echo(
            f"Error: '{cwd}' is not a Git repository root. "
            "Run reveille init from within a repository root.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    _validate_output_path(output, cwd)

    from reveille.init import write_init_config, write_mailmap_template

    try:
        written_path = write_init_config(output, force=force)
        typer.echo(f"Configuration file written to: {written_path}")
    except ReveilleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc

    if mailmap:
        try:
            mailmap_result = write_mailmap_template(cwd / ".mailmap", force=force)
        except ReveilleError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
        if mailmap_result is not None:
            typer.echo(f".mailmap template written to: {mailmap_result}")
        else:
            typer.echo(".mailmap already exists — skipped.")


@app.command()
def capabilities(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format. Accepted values: text, json.",
        ),
    ] = "text",
) -> None:
    """Describe what Reveille can and cannot do, for a person or a program."""
    from reveille.capabilities import build_capabilities, render_text

    if output_format not in {"text", "json"}:
        typer.echo(
            f"Error: unsupported format '{output_format}'. Accepted values: text, json.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    document = build_capabilities(app, ExitCode)
    if output_format == "json":
        typer.echo(json.dumps(document, indent=2))
    else:
        typer.echo(render_text(document))


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
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        typer.echo(
            f"Error: {flag_name} must be in YYYY-MM-DD format, got '{value}'.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
