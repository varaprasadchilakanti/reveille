"""The `reveille` command a user installs, run as a separate process.

Every other end-to-end test calls the Typer application in-process, which
cannot see the console-script entry point in `pyproject.toml`, the shebang,
or the exit status a shell receives. A packaging fault there would leave
the rest of the suite green while `pipx install reveille` gave a command
that does not start. These tests run the script the environment installed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from reveille import __version__


def _installed_command() -> Path:
    """The console script beside this interpreter, as `pip` and `poetry` place it."""
    bindir = Path(sys.executable).parent
    for name in ("reveille", "reveille.exe"):
        if (bindir / name).is_file():
            return bindir / name
    pytest.fail(
        f"no installed `reveille` command beside {sys.executable}; is the package installed?"
    )


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_installed_command()), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("installed") / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day in (1, 2):
        (path / "a.txt").write_text(f"{day}\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Ana",
            "GIT_AUTHOR_EMAIL": "ana@e.test",
            "GIT_COMMITTER_NAME": "Ana",
            "GIT_COMMITTER_EMAIL": "ana@e.test",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    return path


@pytest.mark.e2e
class TestTheInstalledCommand:
    def test_it_starts_and_states_its_version(self, tmp_path: Path) -> None:
        result = _run("--version", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert __version__ in result.stdout

    def test_it_writes_a_report_where_it_is_told(self, repo: Path, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        result = _run("generate", "--repo", str(repo), "--output", str(out), cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert out.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html>")

    def test_a_negative_answer_reaches_the_shell_as_one(self, repo: Path, tmp_path: Path) -> None:
        result = _run("who-changed", "nowhere.txt", "--repo", str(repo), cwd=tmp_path)

        assert result.returncode == 1, result.stderr
        # A crash also exits 1; a negative answer says so without a traceback.
        assert "Traceback" not in result.stderr
        assert "nowhere.txt" in result.stderr + result.stdout

    def test_an_unusable_argument_reaches_the_shell_as_two(self, tmp_path: Path) -> None:
        result = _run("summary", "--repo", str(tmp_path / "missing"), cwd=tmp_path)

        assert result.returncode == 2

    def test_a_summary_on_stdout_is_json_and_nothing_else(self, repo: Path, tmp_path: Path) -> None:
        result = _run("summary", "--repo", str(repo), "--format", "json", cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["totals"]["commits"] == 2
