# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Every command refuses a `--format` it does not offer in one sentence, naming the value."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.e2e


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


@pytest.mark.parametrize(
    ("command", "choices"),
    [
        (["generate"], "html, json or csv"),
        (["summary"], "text, json or markdown"),
        (["state"], "text, json, markdown or line"),
        (["brief"], "text, json, markdown or line"),
        (["who-changed", "a.txt"], "text or json"),
    ],
)
@pytest.mark.parametrize("given", ["xml", "JSON"])
def test_an_unoffered_format_is_refused_in_the_same_words(
    repo: Path, command: list[str], choices: str, given: str
) -> None:
    result = CliRunner().invoke(app, [*command, "--repo", str(repo), "--format", given])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert result.stderr == f"Error: --format must be {choices}, not '{given}'.\n"


def test_generate_json_still_writes_plain_stderr(repo: Path) -> None:
    """Positive control: a valid `generate --format json` keeps stderr as text."""
    result = CliRunner().invoke(
        app,
        [
            "generate",
            "-q",
            "--repo",
            str(repo),
            "--format",
            "json",
            "-o",
            "-",
            "--since",
            "2999-01-01",
        ],
    )

    assert result.exit_code == ExitCode.NEGATIVE
    assert result.stderr.startswith("Error: No commits found"), result.stderr


def test_a_config_file_format_names_the_value_given(repo: Path, tmp_path: Path) -> None:
    config = tmp_path / "bad.toml"
    config.write_text('[report]\nformat = "xml"\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "--config", str(config)])

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert result.stderr == (
        "Configuration error: --format / report.format: Input should be 'html', 'json' or "
        "'csv', not 'xml'\n"
    )
