# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Only `-` itself means standard output; `./-` is a file named `-`.

`Path("./-")` is `Path("-")`, so `-o ./-`, and `output = "./-"` in a
`reveille.toml`, wrote to stdout. From a configuration file that also passed
over the checks a configured output path gets.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.config import output_path

pytestmark = pytest.mark.e2e


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    identity = ["-c", "user.name=A", "-c", "user.email=a@e.test"]
    subprocess.run(
        ["git", *identity, "commit", "-q", "--allow-empty", "-m", "x"], cwd=path, check=True
    )
    monkeypatch.chdir(path)
    return path


@pytest.mark.parametrize("text", ["./-", "././-", ".//-"])
def test_a_spelling_of_a_file_named_dash_is_not_stdout(text: str) -> None:
    assert output_path(text) == Path.cwd() / "-"


def test_dash_itself_is_stdout() -> None:
    assert output_path("-") == Path("-")


def test_generate_writes_a_file_named_dash(repo: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "-q", "-o", "./-"])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert (repo / "-").is_file()
    assert "<html" not in result.stdout


def test_generate_to_dash_still_writes_stdout(repo: Path) -> None:
    """Control."""
    result = CliRunner().invoke(app, ["generate", "-q", "--format", "json", "-o", "-"])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert result.stdout.startswith("{")
    assert not (repo / "-").exists()


def test_init_writes_a_file_named_dash(repo: Path) -> None:
    result = CliRunner().invoke(app, ["init", "-o", "./-"])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert (repo / "-").is_file()


def test_a_configured_dash_file_gets_the_configured_output_checks(repo: Path) -> None:
    (repo / "reveille.toml").write_text('[report]\noutput = "./-"\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["generate", "-q"])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.output
    assert "does not end in .html" in " ".join(result.stderr.split())
    assert "<html" not in result.stdout
