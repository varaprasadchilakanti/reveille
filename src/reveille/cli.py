# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""CLI entry point for Reveille (`reveille = "reveille.cli:app"`).

Parses flags, builds a ReportConfig and delegates; no business logic.
Exit codes are a contract: see `ExitCode` and docs/USER_GUIDE.md.
"""

from __future__ import annotations

import contextlib
import datetime
import enum
import itertools
import json
import logging
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, NoReturn, TextIO, cast, get_args

import typer
from typer.core import TyperCommand, TyperGroup
from typer.main import get_command
from typer.models import CommandFunctionType

from reveille import __version__
from reveille.config import OutputFormat, ReportConfig, ReportConfigKwargs
from reveille.domain.models import ProgressEvent
from reveille.domain.repositories import MAX_SEARCH_DEPTH
from reveille.exceptions import (
    ConfigurationError,
    EmptyRepositoryError,
    NoRepositoryReadError,
    ReveilleError,
)
from reveille.git_directory import holds_a_git_directory
from reveille.undecoded import json_text

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
        (0x2028, 0x2029),  # line and paragraph separators: a line break to many readers
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
#: Whether stderr is silenced: only while a check runs to learn whether it would refuse.
_stderr_muted = {"on": False}

_LEVELS = {"Error: ": "error", "Warning: ": "warning", "Note: ": "note"}


def _err(message: str) -> None:
    """Write one message to stderr, with terminal control characters escaped.

    Under `--format json` the message is one JSON object on its own line,
    `{"level": "error" | "warning" | "note", "message": ...}`: a configuration
    error is an error, and any other message without a prefix is a note.

    Args:
        message: The message to print, starting "Error: ", "Warning: " or "Note: ".
    """
    if _stderr_muted["on"]:
        return
    if _stderr_json["on"]:
        level = "error" if message.startswith("Configuration error: ") else "note"
        text = message
        for prefix, name in _LEVELS.items():
            if message.startswith(prefix):
                level, text = name, message.removeprefix(prefix)
        typer.echo(json_text({"level": level, "message": text}), err=True)
        return
    typer.echo(_printable(message), err=True)


def _say(text: str, *, nl: bool = True, answer: bool = True) -> None:
    """Write to stdout, and say so when it cannot be done.

    A reader that stopped early (`| head`) ends the run quietly with exit 0, as
    it chose. A full disk, or a closed stdout for an answer, cannot deliver the
    answer, so it exits 2 rather than 0 or Click's 1. Stdout is then pointed at
    the null device, so the interpreter's last flush cannot fail again.

    Args:
        text: What to write.
        nl: Whether to end it with a newline.
        answer: False for a confirmation, such as a written file's path, which is
            left out, not an error, when stdout is closed.

    Raises:
        typer.Exit: SUCCESS for a reader that stopped, CANNOT_RUN otherwise.
    """
    if sys.stdout is None:
        if not answer:
            return
        _err("Error: standard output is closed, so the answer has nowhere to go.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    try:
        typer.echo(text, nl=nl)
        sys.stdout.flush()
    except BrokenPipeError as exc:
        _discard_stdout()
        raise typer.Exit(code=ExitCode.SUCCESS) from exc
    except OSError as exc:
        _discard_stdout()
        if not answer:
            return
        _err(f"Error: the output could not be written to standard output: {exc.strerror}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc


def _show_help(ctx: Any) -> None:
    """Write a command's help to stdout, failing as `_say` does when it cannot be written.

    Typer's help is printed by Rich from inside `get_help`, so the writing is
    caught around that call, not around an echo of what it returns.

    Args:
        ctx: The Click context of the command whose help is wanted.

    Raises:
        typer.Exit: SUCCESS for a reader that stopped, CANNOT_RUN when the help
            cannot be written.
    """
    if sys.stdout is None:
        _err("Error: standard output is closed, so the answer has nowhere to go.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    try:
        text = ctx.get_help()
        if text:  # without Rich, Click returns the help instead of printing it
            typer.echo(text)
        sys.stdout.flush()
    except BrokenPipeError as exc:
        _discard_stdout()
        raise typer.Exit(code=ExitCode.SUCCESS) from exc
    except SystemExit as exc:
        # Rich's own answer to a broken pipe (`Console.on_broken_pipe`) is exit 1,
        # the negative answer; a reader that stopped early chose to, so it is 0.
        if exc.code != 1:
            raise
        raise typer.Exit(code=ExitCode.SUCCESS) from exc
    except OSError as exc:
        _discard_stdout()
        _err(f"Error: the output could not be written to standard output: {exc.strerror}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc


def _help_option_callback(ctx: Any, _param: Any, value: bool) -> None:
    """Show the help for `--help` or `-h`, through `_show_help`."""
    if value and not ctx.resilient_parsing:
        _show_help(ctx)
        ctx.exit()


def _discard_stdout() -> None:
    """Point stdout's descriptor at the null device, dropping what is buffered."""
    with contextlib.suppress(OSError, ValueError):
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


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
        if error.get("type") == "literal_error":
            # A choice, as `--format` refusals say: name the value given.
            message += f", not {error.get('input')!r}"
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
            self.stream.write(json_text(entry) + "\n")
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


def _why_git_cannot_start(message: str) -> str:
    """Return Git's own reason from GitPython's import-time failure, or a plain one.

    Args:
        message: The ImportError text GitPython raises when `git version` fails.

    Returns:
        Git's first error line, or a sentence saying no Git was found on PATH.
    """
    _, found, stderr = message.partition("stderr: '")
    lines = [line.strip() for line in stderr.rstrip("'").splitlines()] if found else []
    reasons = [line for line in lines if line and not line.startswith("hint:")]
    return reasons[0] if reasons else "no working `git` program was found on PATH"


def _exit_as_defect(exc: Exception) -> NoReturn:
    """Say an error nobody anticipated is a defect, and exit 2, never 1.

    Args:
        exc: The error.
    """
    _logger.debug("Unexpected error", exc_info=True)
    _err(f"Error: {type(exc).__name__}: {exc}. This is a defect in Reveille; please report it.")
    # A last flush of a stdout that cannot be written would turn the exit into 120.
    _discard_stdout()
    sys.exit(ExitCode.CANNOT_RUN)


def _file_path(value: str | Path) -> Path:
    """Read `--output` as a file's path, refusing one spelt as a directory.

    `Path` drops a trailing slash, so `-o reports/` would have written a file
    named `reports`.

    Args:
        value: The option as given, or its default.

    Returns:
        The path.

    Raises:
        typer.BadParameter: If the path ends with a separator.
    """
    text = str(value)
    if text.endswith(("/", os.sep)) and text != os.sep:
        raise typer.BadParameter(
            f"{text!r} ends with {text[-1]!r}, so it names a directory, not a file. "
            "Give a file name in it."
        )
    return Path(text)


#: The commands whose stderr is JSON lines under `--format json`.
_JSON_STDERR_COMMANDS = frozenset(
    {"summary", "brief", "state", "repos", "who-changed", "capabilities"}
)


def _asks_for_json(words: list[str]) -> bool:
    """Return whether the last `--format` in a command line is `json`."""
    asked = None
    for word, following in zip(words, [*words[1:], None], strict=True):
        if word == "--format":
            asked = following
        elif word.startswith("--format="):
            asked = word.removeprefix("--format=")
        elif word == "--":
            break
    return asked == "json"


#: Click's usage error, from the Click that Typer runs on: Typer 0.27 carries its own.
_UsageError: type[Exception] = next(
    c for c in typer.BadParameter.__mro__ if c.__name__ == "UsageError"
)


class _Group(TyperGroup):
    """The command group: a usage error is a JSON line where the command's messages are."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        """Keep the command line, which Click consumes before a subcommand fails on it.

        Args:
            ctx: The group's context.
            args: The words after the program name.

        Returns:
            What Click's parser leaves for the subcommand.
        """
        ctx.meta["reveille.words"] = list(args)
        if not args and self.no_args_is_help and not ctx.resilient_parsing:
            # No command is not a command: the help is given, and the exit is 2 however
            # the help went.
            with contextlib.suppress(typer.Exit):
                _show_help(ctx)
            raise typer.Exit(code=ExitCode.CANNOT_RUN)
        return super().parse_args(ctx, args)

    def get_help_option(self, ctx: Any) -> Any:
        """Return `--help`, shown through `_show_help`.

        Args:
            ctx: The group's context.

        Returns:
            The help option.
        """
        return _through_show_help(super().get_help_option(ctx))

    def invoke(self, ctx: Any) -> Any:
        """Run the subcommand; under `--format json`, its usage errors are JSON too.

        Args:
            ctx: The group's context.

        Returns:
            What the subcommand returns.

        Raises:
            typer.Exit: CANNOT_RUN, after the JSON error line.
        """
        try:
            return super().invoke(ctx)
        except _UsageError as exc:
            words = [w for w in ctx.meta.get("reveille.words", []) if not w.startswith("-")]
            command = words[0] if words else ""
            if command not in _JSON_STDERR_COMMANDS or not _asks_for_json(
                ctx.meta["reveille.words"]
            ):
                raise
            _stderr_json["on"] = True
            message = cast(Any, exc).format_message().rstrip(".")
            _err(
                f"Error: {message}. Run `reveille capabilities --command {command} "
                "--format json` for its options."
            )
            raise typer.Exit(ExitCode.CANNOT_RUN) from exc


def _through_show_help(option: Any) -> Any:
    """Point a help option at `_show_help`; None stays None."""
    if option is not None:
        option.callback = _help_option_callback
    return option


class _Command(TyperCommand):
    """A command whose `--help` is shown through `_show_help`."""

    def get_help_option(self, ctx: Any) -> Any:
        """Return `--help`, shown through `_show_help`.

        Args:
            ctx: The command's context.

        Returns:
            The help option.
        """
        return _through_show_help(super().get_help_option(ctx))


class _App(typer.Typer):
    """The Typer application, with an exit code for errors nobody anticipated."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Run the CLI; an uncaught exception exits 2 (cannot run), never 1.

        Python exits 1 on an uncaught exception, which the contract reserves for
        a negative answer. The traceback goes to the debug log (`--verbose`).
        """
        try:
            os.getcwd()
        except FileNotFoundError:
            _err(
                "Error: the current directory no longer exists (it was deleted or moved). "
                "Change to a directory that exists, and run Reveille again."
            )
            sys.exit(ExitCode.CANNOT_RUN)
        try:
            return super().__call__(*args, **kwargs)
        except ImportError as exc:
            if not str(exc).startswith("Failed to initialize"):
                _exit_as_defect(exc)  # a bare `raise` would pass the handler below, and exit 1
            _logger.debug("GitPython could not start Git", exc_info=True)
            _err(
                f"Error: Git could not be started: {_why_git_cannot_start(str(exc))}. Install "
                "Git 2.24 or later, put it on PATH, and check your Git configuration."
            )
            sys.exit(ExitCode.CANNOT_RUN)
        except Exception as exc:
            _exit_as_defect(exc)

    def command(
        self, name: str | None = None, *, cls: type[TyperCommand] | None = None, **kwargs: Any
    ) -> Callable[[CommandFunctionType], CommandFunctionType]:
        """Register a command, as `_Command` unless another class is given.

        Args:
            name: The command's name.
            cls: Its class; `_Command` when not given.
            **kwargs: As for `typer.Typer.command`.

        Returns:
            Typer's decorator.
        """
        return super().command(name, cls=cls or _Command, **kwargs)


app = _App(
    cls=_Group,
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
        _say(f"reveille {__version__}")
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
    _exit_cleanly_when_stopped()


def _stop(signum: int, frame: object) -> None:
    """Exit as a terminated process does, through every `finally` on the way out."""
    raise SystemExit(128 + signum)


def _exit_cleanly_when_stopped() -> None:
    """Make SIGTERM and SIGHUP exit 128 + N by raising, so a half-written file is removed.

    By default the process stops where it is, and the `.tmp` beside the output
    stays. SIGHUP is sent when a terminal closes; Windows has none. A handler
    someone else installed is left in place; only the main thread can install one.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None and signal.getsignal(signum) is signal.SIG_DFL:
            signal.signal(signum, _stop)


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
    elif holds_a_git_directory(repo_path):
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


def _refuse_what_is_not_a_file(output: Path, example: str) -> None:
    """Refuse an output path that is a directory, a device, a pipe or a socket, or unusable.

    Args:
        output: The output path as given.
        example: A file name to suggest when it is a directory.

    Raises:
        typer.Exit: ExitCode.CANNOT_RUN if the path is refused.
    """
    try:
        mode = output.stat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:  # a name too long, a loop of links
        _err(f"Error: output path '{output}' cannot be used: {exc.strerror}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    if stat.S_ISDIR(mode):
        _err(
            f"Error: output path '{output}' is a directory. Give a file name, "
            f"for example '{output / example}'."
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    if not stat.S_ISREG(mode):
        _err(
            f"Error: output path '{output}' is not a regular file (a device, a named pipe "
            "or a socket). Give a file name; `-o -` writes to standard output."
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)


#: How each report Reveille writes begins. The HTML title has stood since the first renderer.
_REPORT_STARTS = {
    "html": ("<!DOCTYPE html>", "Reveille Report</title>"),
    "json": ('{\n  "schema_version"', '"schema_version"'),
    "csv": ("rank,name,email,", "rank,name,email,"),
}


def _written_by_reveille(path: Path, output_format: str) -> bool:
    """Whether `path` is missing, or begins as a Reveille report does.

    A directory cannot be read and a pipe reads as empty (opened without waiting), so
    neither passes; a symbolic link is replaced by the write, not followed.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            head = handle.read(4096).decode("utf-8", errors="replace").lstrip("\ufeff")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    start, marker = _REPORT_STARTS[output_format]
    return head.startswith(start) and marker in head


def _refuse_what_a_config_cannot_replace(output: Path, output_format: str) -> None:
    """Refuse a discovered config's output that is not a report, or would replace another file.

    A committed `reveille.toml` could name `src/app.py` or an ignored `.env`, and the
    report replaced it; or `vendor.git/HEAD`, a bare repository's own file.

    Raises:
        typer.Exit: ExitCode.CANNOT_RUN if the path is refused.
    """
    if output.suffix.casefold() != ".html":
        _err(
            f"Error: the configuration file sets an output path that does not end in .html: "
            f"'{output}'. A reveille.toml is discovered automatically, so it may come from a "
            "repository you do not control. Pass --output explicitly to write there."
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    written = output if output_format == "html" else output.with_suffix(f".{output_format}")
    if not _written_by_reveille(written, output_format):
        _err(
            f"Error: the configuration file sets an output path that would replace "
            f"'{written}', which is not a Reveille report. Pass --output explicitly to "
            "replace it."
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)


def _in_a_git_directory(path: Path) -> bool:
    """Return whether a directory above `path` is a Git directory, any repository's.

    Told by its files, as Git tells one; a bare repository's has no `.git` in its
    name, and need not be the one read.

    Args:
        path: A resolved path.

    Returns:
        True when a parent of `path` is one.
    """
    return any(holds_a_git_directory(parent) for parent in path.parents)


def _validate_output_path(
    output: Path,
    repo_path: Path,
    *,
    from_config: bool = False,
    example: str = "reveille-report.html",
    output_format: str = "html",
) -> None:
    """Validate the output path for traversal and the repository boundary.

    Refuses `..`, a Git directory, a directory, a device, a pipe or a socket, and a
    path the system cannot use; warns outside the repository.

    Args:
        output: The output path as given, before resolution.
        repo_path: The resolved repository root.
        from_config: An auto-discovered (untrusted) file supplied the path.
        example: A file name to suggest when the path is a directory.
        output_format: The format to be written, which names the file replaced.

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
    if (
        inside_git_dir
        or any(part.casefold() == ".git" for part in (*output.parts, *output.resolve().parts))
        or _in_a_git_directory(output.resolve())
    ):
        _err(
            f"Error: output path '{output}' is inside a Git directory. Reveille does "
            "not write into Git's own files. Choose another path.",
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    _refuse_what_is_not_a_file(output, example)
    if from_config:
        _refuse_what_a_config_cannot_replace(output, output_format)

    if ".." in output.parts:
        _err(
            f"Error: output path '{output}' contains '..'. Give the same place as an "
            f"absolute path, '{Path(os.path.normpath(Path.cwd() / output))}', or a path "
            "below the current directory.",
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    if not output.resolve().is_relative_to(repo_path):
        _err(
            f"Warning: output path resolves outside the repository root "
            f"'{repo_path}'. Verify this is intentional.",
        )


def _output_path_refused(check: Callable[[], None]) -> bool:
    """Return whether `check`, a call of `_validate_output_path`, refuses, saying nothing."""
    _stderr_muted["on"] = True
    try:
        check()
    except typer.Exit:
        return True
    finally:
        _stderr_muted["on"] = False
    return False


def _refuse_a_repository_that_cannot_be_read(repo_path: Path) -> None:
    """Exit 2, in the reader's words, if the repository cannot be opened.

    Raises:
        typer.Exit: ExitCode.CANNOT_RUN if it cannot.
    """
    from reveille.adapters.git_reader import GitReader

    try:
        GitReader(repo_path)
    except ReveilleError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc


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
        _print_notices(notices)
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.NEGATIVE) from exc
    except ReveilleError as exc:
        spinner.complete()
        _print_notices(notices)
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    spinner.complete()
    _print_notices(notices)
    if to_stdout:
        _say(text, nl=not text.endswith("\n"))
        return
    for path in written:
        _say(_printable(f"Report written to: {path}"), answer=False)


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
        typer.Option(
            "--output",
            "-o",
            help="Where to write the report, or - for stdout. The default's extension follows "
            "--format: .html, .json or .csv.",
            parser=_file_path,
            metavar="PATH",
        ),
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
                "Bound every list of people to this many: in JSON with the full total "
                "beside it, in CSV, and in the HTML. Default: every one in JSON and CSV, "
                "1,000 in the HTML."
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
    from reveille.config import describe_unknown_keys, read_config_file

    _configure_logging(verbose)
    _check_report_format(output_format)

    config_kwargs: ReportConfigKwargs = cast(ReportConfigKwargs, {})
    _auto_discovered = config is None
    _config_path = config if config is not None else _discover_config()
    if _config_path is not None:
        try:
            config_kwargs, unknown_keys = read_config_file(_config_path)
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
        if unknown_keys:
            _err(f"Note: {_config_path}: {describe_unknown_keys(unknown_keys)}")
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

        def check() -> None:
            _validate_output_path(
                Path(merged.get("output_path", output)),
                merged["repo_path"],
                from_config=_output_from_config,
                output_format=str(merged.get("output_format", "html")),
            )

        # The default path is made from `--repo`: when `--repo` is the problem, say
        # so, not that the path made from it cannot be used.
        if _output_path_refused(check):
            _refuse_a_repository_that_cannot_be_read(merged["repo_path"])
        check()

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
        # A note can change how a negative answer reads (a shallow clone, a
        # directory not searched), so it is given with it.
        _print_notices(notices)
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.NEGATIVE) from exc
    except NoRepositoryReadError as exc:
        # The rows are the diagnosis, so they are given before the exit says
        # that nothing was read.
        _print_notices(notices)
        answer = _printable(exc.answer)
        with contextlib.suppress(typer.Exit):  # delivered or not, nothing was read
            _say(answer, nl=not answer.endswith("\n"), answer=False)
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    except ReveilleError as exc:
        _print_notices(notices)
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    _print_notices(notices)
    # The text carries repository-chosen names, so it is escaped like
    # stderr; json.dumps already escapes control characters.
    text = _printable(text)
    _say(text, nl=not text.endswith("\n"))


def _check_query_format(output_format: str, allowed: tuple[str, ...] = ("text", "json")) -> None:
    """Refuse a --format the command does not offer; under json, stderr is JSON too."""
    _stderr_json["on"] = output_format == "json" and "json" in allowed
    if output_format not in allowed:
        choices = ", ".join(allowed[:-1]) + f" or {allowed[-1]}"
        _err(f"Error: --format must be {choices}, not {output_format!r}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)


def _check_report_format(output_format: str | None) -> None:
    """Refuse a `generate --format` it does not offer, as the other commands refuse one.

    Only a refused one goes through `_check_query_format`: a valid `json` there would
    turn stderr to JSON, which `generate` does not do.
    """
    if output_format is not None and output_format not in get_args(OutputFormat):
        _check_query_format(output_format, get_args(OutputFormat))


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
    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown"))
    from reveille.services.report import summary_text

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
    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown", "line"))
    from reveille.services.report import brief_text

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
    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown", "line"))
    from reveille.services.report import state_text

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
    _configure_logging(verbose)
    _check_query_format(output_format, ("text", "json", "markdown", "csv"))
    from reveille.services.report import repositories_text

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
    _configure_logging(verbose)
    _check_query_format(output_format)
    from reveille.services.report import who_changed_text

    root = _root(repo)
    from reveille.adapters.git_reader import GitReader

    try:
        # Opened first: "outside the repository '/tmp'" named a repository that is not one.
        GitReader(root)
    except ReveilleError as exc:
        _err(f"Error: {exc}")
        raise typer.Exit(code=ExitCode.CANNOT_RUN) from exc
    relative = _repository_path(path, root)
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

    _say(_printable(f"Repository at {resolved} is valid."), answer=False)


@app.command()
def init(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Destination path for the generated configuration file, or - for stdout.",
            parser=_file_path,
            metavar="PATH",
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
    by --output; `-o -` prints it instead) with every key present and
    commented out, showing its default. Uncomment and edit only the keys you want to override. Pass
    --mailmap to also generate an annotated .mailmap template at the
    repository root.
    """
    from reveille.init import (
        DEFAULT_CONFIG_TEMPLATE,
        refuse_symlink,
        write_init_config,
        write_mailmap_template,
    )

    if str(output) == "-":
        # As for `generate --output -`: the file's text, to look at or to pipe.
        if mailmap:
            _err("Error: --mailmap writes a file, so it is not used with --output -.")
            raise typer.Exit(code=ExitCode.CANNOT_RUN)
        _say(DEFAULT_CONFIG_TEMPLATE, nl=False)
        return
    cwd = Path(".").resolve()
    if not (cwd / ".git").exists():
        _err(
            f"Error: '{cwd}' is not a Git repository root. "
            "Run reveille init from within a repository root.",
        )
        raise typer.Exit(code=ExitCode.CANNOT_RUN)

    _validate_output_path(output, cwd, example="reveille.toml")

    try:
        if mailmap:
            refuse_symlink(cwd / ".mailmap")  # first, so a refusal writes neither file
        written_path = write_init_config(output, force=force)
        _say(f"Configuration file written to: {written_path}", answer=False)
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
            _say(f".mailmap template written to: {mailmap_result}", answer=False)
        else:
            _say(".mailmap already exists; skipped.", answer=False)


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

    _check_query_format(output_format)

    document = build_capabilities(get_command(app), ExitCode)
    if command is not None:
        narrowed = command_capabilities(document, command)
        if narrowed is None:
            known = ", ".join(c["name"] for c in document["commands"])
            _err(f"Error: no command {command!r}; the commands are {known}.")
            raise typer.Exit(code=ExitCode.CANNOT_RUN)
        _say(
            json.dumps(narrowed, indent=2)
            if output_format == "json"
            else render_command_text(narrowed)
        )
        return
    if output_format == "json":
        _say(json.dumps(document, indent=2))
    else:
        _say(render_text(document))


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

    _check_query_format(output_format, ("markdown", "skill"))
    _say(guide(output_format), nl=False)


@app.command()
def help(
    ctx: typer.Context,
    command: Annotated[
        str | None, typer.Argument(help="A command to show the help of, as `<command> --help`.")
    ] = None,
) -> None:
    """Display help information for all available commands, or for one."""
    root = ctx.parent if ctx.parent is not None else ctx
    if command is None:
        _show_help(root)
        return
    group = root.command
    sub = group.get_command(root, command) if isinstance(group, TyperGroup) else None
    if sub is None:
        known = ", ".join(group.list_commands(root)) if isinstance(group, TyperGroup) else ""
        _err(f"Error: no command {command!r}; the commands are {known}.")
        raise typer.Exit(code=ExitCode.CANNOT_RUN)
    _show_help(type(ctx)(sub, info_name=command, parent=root))


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
