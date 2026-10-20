# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A discovered reveille.toml cannot make the report replace a file that is not a report.

The file is found from the working directory, so a repository can commit one. Its
`output` replaced uncommitted work in `src/b.py`, an ignored `.env`, and the `HEAD` of a
bare repository inside the tree, and the run exited 0.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_WORK = "uncommitted work\n"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _configure(repo: Path, output: str, output_format: str = "html") -> None:
    (repo / "reveille.toml").write_text(
        f'[report]\noutput = "{output}"\nformat = "{output_format}"\n', encoding="utf-8"
    )


def _generate() -> tuple[int, str]:
    result = CliRunner().invoke(app, ["generate", "--quiet"])
    return result.exit_code, result.stderr


@pytest.mark.parametrize("target", ["src/b.py", ".env", "vendor.git/HEAD", "notes.HTML.bak"])
def test_a_path_that_is_not_a_report_is_refused(repo: Path, target: str) -> None:
    (repo / target).parent.mkdir(parents=True, exist_ok=True)
    (repo / target).write_text(_WORK, encoding="utf-8")
    _configure(repo, target)

    code, stderr = _generate()

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "does not end in .html" in stderr
    assert (repo / target).read_text(encoding="utf-8") == _WORK


def test_an_html_file_that_is_not_a_report_is_kept(repo: Path) -> None:
    page = repo / "docs" / "index.html"
    page.parent.mkdir()
    page.write_text("<!DOCTYPE html>\n<title>Docs</title>\n", encoding="utf-8")
    _configure(repo, "docs/index.html")

    code, stderr = _generate()

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "which is not a Reveille report" in stderr
    assert page.read_text(encoding="utf-8").endswith("<title>Docs</title>\n")


@pytest.mark.parametrize("output_format", ["html", "json", "csv"])
def test_the_config_replaces_its_own_report(repo: Path, output_format: str) -> None:
    _configure(repo, "reports/activity.html", output_format)
    (repo / "reports").mkdir()

    assert _generate()[0] == ExitCode.SUCCESS, "positive control: the first report is written"
    code, stderr = _generate()

    assert code == ExitCode.SUCCESS, stderr


@pytest.mark.parametrize(("output_format", "start"), [("json", "{}\n"), ("csv", "a,b\n")])
def test_the_sibling_a_format_writes_is_checked(repo: Path, output_format: str, start: str) -> None:
    sibling = repo / f"data.{output_format}"
    sibling.write_text(start, encoding="utf-8")
    _configure(repo, "data.html", output_format)

    code, stderr = _generate()

    assert code == ExitCode.CANNOT_RUN, stderr
    assert sibling.read_text(encoding="utf-8") == start


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions")
def test_a_sibling_that_cannot_be_read_is_kept(repo: Path) -> None:
    sibling = repo / "data.json"
    sibling.write_text(_WORK, encoding="utf-8")
    sibling.chmod(0)
    _configure(repo, "data.html", "json")
    try:
        code, stderr = _generate()
    finally:
        sibling.chmod(0o644)

    assert code == ExitCode.CANNOT_RUN, stderr
    assert sibling.read_text(encoding="utf-8") == _WORK


def test_a_sibling_that_is_not_a_file_is_refused(repo: Path) -> None:
    (repo / "data.csv").mkdir()
    _configure(repo, "data.html", "csv")

    code, stderr = _generate()

    assert code == ExitCode.CANNOT_RUN, stderr
    assert "which is not a Reveille report" in stderr
    assert (repo / "data.csv").is_dir()


def test_an_output_the_user_names_is_theirs_to_replace(repo: Path) -> None:
    (repo / "src").mkdir()
    (repo / "src" / "b.py").write_text(_WORK, encoding="utf-8")
    _configure(repo, "src/b.py")

    result = CliRunner().invoke(app, ["generate", "--quiet", "--output", "src/b.py"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert (repo / "src" / "b.py").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
