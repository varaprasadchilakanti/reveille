"""CLI entry point for Reveille.

Defines three public commands: generate, version, validate.
Responsible for flag parsing, boundary validation, constructing
a ReportConfig, and delegating to the application service.
Contains no business logic.

Entry point registered in pyproject.toml:
    reveille = "reveille.cli:app"
"""

from __future__ import annotations

import datetime
import itertools
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, ClassVar, cast

import typer

from reveille import __version__
from reveille.config import ReportConfig, ReportConfigKwargs
from reveille.exceptions import ConfigurationError, RevelleError

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

    def begin(self, label: str) -> None:
        """Start the animated indicator for a new pipeline stage.

        Args:
            label: Human-readable stage name written to stderr.
        """
        self._label = label
        self._stop_event.clear()
        self._active = True
        self._thread = threading.Thread(target=self._run, args=(label,), daemon=True)
        self._thread.start()

    def complete(self) -> None:
        """Stop the current animation and write the completion line.

        No-op if begin() has not been called or if already completed.
        """
        if not self._active:
            return
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
        sys.stderr.write(f"\r  {label} ...   done\n")
        sys.stderr.flush()


def _make_progress_callback(spinner: _StageSpinner) -> Callable[[str], None]:
    """Return a progress callback that drives the given spinner.

    On each invocation, completes the previous stage animation and
    starts a new one for the incoming label.

    Args:
        spinner: The _StageSpinner instance to drive.

    Returns:
        A callable suitable for passing as on_progress to generate_report.
    """

    def _callback(label: str) -> None:
        spinner.complete()
        spinner.begin(label)

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
        no_ranking: Whether ranking is disabled.

    Returns:
        A merged ReportConfigKwargs ready for ReportConfig construction.
    """
    merged: dict[str, Any] = dict(config_kwargs)
    resolved_repo = repo.resolve()
    merged["repo_path"] = resolved_repo

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
    if no_ranking:
        merged["ranking_enabled"] = False

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
    no_ranking: Annotated[
        bool,
        typer.Option("--no-ranking", help="Omit the contributor ranking table from the output."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to a TOML configuration file."),
    ] = None,
) -> None:
    """Generate an HTML performance report for the target repository."""
    from reveille.config import load_config_from_toml
    from reveille.services.report import generate_report

    config_kwargs: ReportConfigKwargs = cast(ReportConfigKwargs, {})
    _auto_discovered = config is None
    _config_path = config if config is not None else _discover_config()
    if _config_path is not None:
        try:
            config_kwargs = load_config_from_toml(_config_path)
        except ConfigurationError as exc:
            if _auto_discovered:
                typer.echo(
                    f"Configuration error: auto-discovered {_CONVENTIONAL_CONFIG} "
                    f"contains invalid TOML.\nDetail: {exc}\n"
                    f"Correct the syntax or regenerate the file with: "
                    f"reveille init --force",
                    err=True,
                )
            else:
                typer.echo(f"Configuration error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

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
    )

    try:
        report_config = ReportConfig(**merged)
    except ValueError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    spinner = _StageSpinner()
    try:
        written_path = generate_report(
            report_config,
            on_progress=_make_progress_callback(spinner),
        )
    except RevelleError as exc:
        spinner.complete()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    else:
        spinner.complete()
        typer.echo(f"Report written to: {written_path}")


@app.command()
def validate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the Git repository root."),
    ] = Path("."),
) -> None:
    """Validate that the target path is a readable Git repository with at least one commit."""
    from reveille.adapters.git_reader import GitReader
    from reveille.exceptions import EmptyRepositoryError

    resolved = repo.resolve()
    try:
        reader = GitReader(resolved)
    except RevelleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        reader.read_commits(branch=None, since=None, until=None, exclude_authors=[])
    except EmptyRepositoryError:
        typer.echo(
            f"Error: repository at '{resolved}' contains no commits.",
            err=True,
        )
        raise typer.Exit(code=1) from None
    except RevelleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

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
) -> None:
    """Scaffold an annotated reveille.toml configuration file.

    Writes a fully commented configuration file to the current directory
    (or the path specified by --output) with all keys present and set to
    their defaults. Uncomment and edit only the keys you want to override.
    """
    cwd = Path(".").resolve()
    if not (cwd / ".git").exists():
        typer.echo(
            f"Error: '{cwd}' is not a Git repository root. "
            "Run reveille init from within a repository root.",
            err=True,
        )
        raise typer.Exit(code=1)

    from reveille.init import write_init_config

    try:
        written_path = write_init_config(output, force=force)
        typer.echo(f"Configuration file written to: {written_path}")
    except RevelleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
        typer.Exit: With code 1 if the format is invalid.
    """
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        typer.echo(
            f"Error: {flag_name} must be in YYYY-MM-DD format, got '{value}'.",
            err=True,
        )
        raise typer.Exit(code=1) from exc
