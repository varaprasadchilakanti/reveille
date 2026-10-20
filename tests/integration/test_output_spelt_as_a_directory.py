# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""An output spelt as a directory is refused, and `init -o -` prints the file.

`Path("reports/")` is `Path("reports")`, so `-o reports/` wrote a file named
`reports`. `init -o -` wrote a file named `-`, where `generate -o -` writes to
standard output.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.config import ConfigurationError, load_config_from_toml
from reveille.init import DEFAULT_CONFIG_TEMPLATE

pytestmark = pytest.mark.integration


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=A",
            "-c",
            "user.email=a@e.test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "a",
        ],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("command", ["generate", "init"])
def test_a_trailing_slash_is_refused_and_nothing_is_written(root: Path, command: str) -> None:
    before = sorted(p.name for p in root.iterdir())

    result = CliRunner().invoke(app, [command, "-o", "made/"])

    assert result.exit_code == ExitCode.CANNOT_RUN, result.stderr
    # Click boxes the message, and colours it where Rich detects CI (GITHUB_ACTIONS).
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
    unboxed = " ".join(plain.replace("│", " ").split())
    assert "names a directory, not a file" in unboxed, result.stderr
    assert sorted(p.name for p in root.iterdir()) == before


def test_the_default_output_is_still_accepted(root: Path) -> None:
    result = CliRunner().invoke(app, ["generate", "-q"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert (root / "reveille-report.html").is_file()


def test_a_trailing_slash_in_the_file_is_refused(tmp_path: Path) -> None:
    config = tmp_path / "reveille.toml"
    config.write_text('[report]\noutput = "reports/"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="names a directory"):
        load_config_from_toml(config)


def test_init_to_stdout_prints_the_file_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No repository is needed to read the template."""
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["init", "-o", "-"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert result.stdout == DEFAULT_CONFIG_TEMPLATE
    assert list(tmp_path.iterdir()) == []


def test_init_to_stdout_with_mailmap_is_refused(root: Path) -> None:
    result = CliRunner().invoke(app, ["init", "-o", "-", "--mailmap"])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert not (root / ".mailmap").exists()
