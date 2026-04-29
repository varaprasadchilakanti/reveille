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
from reveille.exceptions import RevelleError

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
        int,
        typer.Option("--min-commits", help="Exclude contributors below this commit threshold."),
    ] = 1,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Override the report title in the HTML output."),
    ] = None,
    no_ranking: Annotated[
        bool,
        typer.Option("--no-ranking", help="Omit the contributor ranking table from the output."),
    ] = False,
) -> None:
    """Generate an HTML performance report for the target repository."""
    from reveille.services.report import generate_report

    since_date = _parse_date(since, "--since") if since else None
    until_date = _parse_date(until, "--until") if until else None

    try:
        config = ReportConfig(
            repo_path=repo.resolve(),
            output_path=output,
            title=title,
            branch=branch,
            since=since_date,
            until=until_date,
            exclude_authors=exclude_author or [],
            min_commits=min_commits,
            ranking_enabled=not no_ranking,
        )
    except ValueError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        written_path = generate_report(config)
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
