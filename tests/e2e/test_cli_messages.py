"""What the command prints when it cannot run.

Found by running the installed tool on bad input. An inverted date range
printed "1 validation error for ReportConfig", a dump of the whole
configuration and a pydantic.dev link, with the actual reason buried
between them; an output path naming a directory printed `[Errno 21]`;
`validate` still asked for a `.git` directory that bare repositories do
not have; and values from a `reveille.toml` reached the terminal with
their control sequences intact, so a file could erase its own warning.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

_RAW_PYDANTIC = ("validation error for", "errors.pydantic.dev", "input_value", "type=")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("messages_repo")
    run = {"cwd": path, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q", "-b", "main"], **run)  # type: ignore[call-overload]
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], **run)  # type: ignore[call-overload]
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@example.com", "commit", "-qm", "a"],
        **run,  # type: ignore[call-overload]
    )
    return path


def _generate(repo: Path, out: Path, *extra: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--output", str(out), *extra]
    )
    return result.exit_code, result.stderr


@pytest.mark.e2e
class TestInvalidOptionsSayWhatIsWrong:
    @pytest.mark.parametrize(
        ("extra", "says"),
        [
            (["--since", "2026-10-05", "--until", "2026-01-01"], "must be earlier than"),
            (["--format", "pdf"], "--format"),
            (["--min-commits", "-5"], "--min-commits"),
        ],
    )
    def test_in_one_plain_line(
        self, repo: Path, tmp_path: Path, extra: list[str], says: str
    ) -> None:
        code, stderr = _generate(repo, tmp_path / "r.html", *extra)

        assert code == ExitCode.CANNOT_RUN
        assert says in stderr
        for raw in _RAW_PYDANTIC:
            assert raw not in stderr, f"{raw!r} leaked into: {stderr}"

    def test_an_output_directory_is_named_as_such(self, repo: Path, tmp_path: Path) -> None:
        code, stderr = _generate(repo, tmp_path)

        assert code == ExitCode.CANNOT_RUN
        assert "is a directory" in stderr
        assert "Errno" not in stderr


@pytest.mark.e2e
def test_validate_does_not_ask_for_a_dot_git_directory(tmp_path: Path) -> None:
    """Bare repositories have none, and are analysed without complaint."""
    plain = tmp_path / "plain"
    plain.mkdir()
    result = CliRunner().invoke(app, ["validate", "--repo", str(plain)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert ".git directory" not in result.stderr
    assert "bare repository" in result.stderr


@pytest.mark.e2e
class TestConfigValuesCannotDriveTheTerminal:
    """A `reveille.toml` may come from a repository somebody else controls."""

    def _run_with_toml(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
    ) -> str:
        work = tmp_path / "work"
        work.mkdir()
        (work / "reveille.toml").write_text(body, encoding="utf-8")
        monkeypatch.chdir(work)
        _, stderr = _generate(repo, tmp_path / "r.html")
        return stderr

    def test_an_unmatched_exclusion(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stderr = self._run_with_toml(
            repo, tmp_path, monkeypatch, '[filters]\nexclude_authors = ["x\\u001b[2Jy"]\n'
        )

        assert "\x1b" not in stderr
        # Exclusions are compared in lower case, so the warning quotes them so.
        assert "x\\x1b[2jy" in stderr.lower(), "positive control: the warning is still shown"

    def test_a_missing_branch(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stderr = self._run_with_toml(
            repo, tmp_path, monkeypatch, '[report]\nbranch = "nope\\u001b[31m"\n'
        )

        assert "\x1b" not in stderr
        assert "nope\\x1b[31m" in stderr


@pytest.mark.e2e
def test_a_warning_starts_its_own_line(capsys: pytest.CaptureFixture[str]) -> None:
    """The progress line stays open while it animates, and a warning raised
    meanwhile was printed on the end of it: "Reading commit history .
    WARNING ...". It now starts on a line of its own."""
    import logging
    import time

    from reveille.cli import _configure_logging, _StageSpinner

    _configure_logging(verbose=False)
    spinner = _StageSpinner()
    spinner.begin("Reading commit history")
    time.sleep(0.05)
    logging.getLogger("reveille.test").warning("matched no commits for: x")
    spinner.complete()

    err = capsys.readouterr().err
    assert "WARNING" in err, "positive control: the warning was printed"
    assert not re.search(r"[^\n]WARNING", err), err


@pytest.mark.e2e
@pytest.mark.parametrize(("count", "says"), [(1, "1 commit)"), (2, "2 commits)")])
def test_the_progress_line_agrees_with_its_count(
    capsys: pytest.CaptureFixture[str], count: int, says: str
) -> None:
    from reveille.cli import _StageSpinner

    spinner = _StageSpinner()
    spinner.begin("Reading commit history")
    spinner.complete(elapsed_seconds=0.0, items_processed=count)

    assert says in capsys.readouterr().err
