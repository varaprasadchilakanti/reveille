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
from pathlib import Path
from typing import Annotated

import typer

from reveille import __version__
from reveille.config import ReportConfig
from reveille.exceptions import ConfigurationError, RevelleError

app = typer.Typer(
    name="reveille",
    help="Generate self-contained HTML performance reports from local Git repositories.",
    add_completion=False,
    no_args_is_help=True,
)


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
    config_kwargs: dict[str, object],
    repo: Path,
    output: Path,
    since: str | None,
    until: str | None,
    branch: str | None,
    title: str | None,
    exclude_author: list[str] | None,
    min_commits: int | None,
    no_ranking: bool,
    heatmap_granularity: str | None,
) -> dict[str, object]:
    """Merge CLI flag values into the base configuration dict.

    CLI flag values always take precedence over configuration file values.
    Flags that were not explicitly set by the user (i.e. still at their
    default) are only applied when no configuration file provided a value.

    Args:
        config_kwargs: Base kwargs loaded from a TOML file, or empty dict.
        repo: Resolved repository path from --repo flag.
        output: Output path from --output flag.
        since: Raw since date string, or None if not provided.
        until: Raw until date string, or None if not provided.
        branch: Branch name, or None if not provided.
        title: Report title override, or None if not provided.
        exclude_author: List of authors to exclude, or None.
        min_commits: Minimum commit threshold.
        no_ranking: Whether ranking is disabled.
        heatmap_granularity: Heatmap resolution string, or None if not provided.

    Returns:
        A merged dict ready for ReportConfig construction.
    """
    merged = dict(config_kwargs)
    merged["repo_path"] = repo.resolve()

    if output != Path("reveille-report.html") or "output_path" not in merged:
        merged["output_path"] = _resolve_output_path(
            output,
            merged["repo_path"],  # type: ignore[arg-type]
        )
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
    if heatmap_granularity is not None:
        merged["heatmap_granularity"] = heatmap_granularity

    return merged


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
    heatmap_granularity: Annotated[
        str | None,
        typer.Option(
            "--heatmap-granularity",
            help=(
                "Heatmap resolution. 'weekly' suits short histories. "
                "'monthly' is the default. 'yearly' suits long histories."
            ),
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to a TOML configuration file."),
    ] = None,
) -> None:
    """Generate an HTML performance report for the target repository."""
    from reveille.config import load_config_from_toml
    from reveille.services.report import generate_report

    config_kwargs: dict[str, object] = {}
    if config is not None:
        try:
            config_kwargs = load_config_from_toml(config)
        except ConfigurationError as exc:
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
        heatmap_granularity,
    )

    try:
        report_config = ReportConfig(**merged)  # type: ignore[arg-type]
    except ValueError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        written_path = generate_report(report_config)
        typer.echo(f"Report written to: {written_path}")
    except RevelleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def validate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the Git repository root."),
    ] = Path("."),
) -> None:
    """Validate that the target path is a readable Git repository."""
    resolved = repo.resolve()
    if not (resolved / ".git").exists():
        typer.echo(f"Error: {resolved} does not contain a .git directory.", err=True)
        raise typer.Exit(code=1)
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
    from reveille.init import write_init_config

    try:
        written_path = write_init_config(output, force=force)
        typer.echo(f"Configuration file written to: {written_path}")
    except RevelleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
