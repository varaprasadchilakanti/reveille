# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A key Reveille does not read is named, not silently ignored.

A misspelt key is a setting that never applied. It is a note, not an error, so
a file written for another version of Reveille still runs.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app
from reveille.config import _KNOWN_KEYS, read_config_file
from reveille.init import write_init_config

pytestmark = pytest.mark.integration

_GUIDE = Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md"


def _unknown(tmp_path: Path, text: str) -> list[str]:
    config = tmp_path / "reveille.toml"
    config.write_text(text, encoding="utf-8")
    return read_config_file(config)[1]


def test_a_misspelt_key_is_named(tmp_path: Path) -> None:
    assert _unknown(tmp_path, '[report]\ntittle = "x"\ntitle = "y"\n') == ["[report] tittle"]


def test_an_unknown_table_is_named_once(tmp_path: Path) -> None:
    assert _unknown(tmp_path, "[colours]\na = 1\nb = 2\n") == ["[colours]"]


def test_an_unknown_weight_is_named(tmp_path: Path) -> None:
    text = "[ranking]\nweights = { commits = 0.30, lines = 0.25, consistency = 0.25, recency = 0.20, reviews = 0 }\n"
    assert _unknown(tmp_path, text) == ["[ranking.weights] reviews"]


def test_a_key_toml_must_quote_is_quoted(tmp_path: Path) -> None:
    assert _unknown(tmp_path, '[report]\n"a b" = 1\n') == ['[report] "a b"']


def test_every_key_the_guide_documents_is_read() -> None:
    """The reference and the reader agree, in both directions."""
    block = re.search(
        r"## TOML Configuration Reference.*?```toml\n(.*?)```", _GUIDE.read_text(), re.S
    )
    assert block, "positive control: the reference block was found"
    documented = tomllib.loads(block.group(1).replace("# format", "format"))
    keys = {f"{s}.{k}" for s, table in documented.items() for k in table}
    keys |= {f"ranking.weights.{k}" for k in documented["ranking"]["weights"]}

    assert keys == {f"{s}.{k}" for s, known in _KNOWN_KEYS.items() for k in known}


def test_the_file_init_writes_names_nothing_unknown(tmp_path: Path) -> None:
    written = write_init_config(tmp_path / "reveille.toml", force=False)
    # Every setting the file offers, commented out or not, is one Reveille reads.
    offered: set[str] = set()
    section = ""
    for line in written.read_text(encoding="utf-8").splitlines():
        if heading := re.fullmatch(r"\[([a-z.]+)\]", line):
            section = heading.group(1)
        elif setting := re.match(r"#? ?([a-z_]+) = ", line):
            offered.add(f"{section}.{setting.group(1)}")

    assert len(offered) == 16, sorted(offered)  # positive control: the parse found them
    assert offered <= {f"{s}.{k}" for s, known in _KNOWN_KEYS.items() for k in known}
    assert read_config_file(written)[1] == []


def _repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "a"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.parametrize("output_format", ["html", "json"])
def test_the_note_is_printed_and_the_run_succeeds(tmp_path: Path, output_format: str) -> None:
    repo = _repo(tmp_path)
    config = tmp_path / "c.toml"
    config.write_text('[report]\ntittle = "x"\n[colours]\n', encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            *("generate", "-q", "--repo", str(repo), "--config", str(config)),
            *("--format", output_format, "--output", str(tmp_path / "out.html")),
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    message = result.stderr
    assert "does not read [report] tittle, [colours], so they have no effect" in message


def test_many_unknown_keys_are_counted_not_listed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    config = tmp_path / "c.toml"
    config.write_text("[report]\n" + "".join(f"k{i} = 1\n" for i in range(5000)), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "generate",
            "-q",
            "--repo",
            str(repo),
            "--config",
            str(config),
            "-o",
            str(tmp_path / "o.html"),
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "[report] k9 and 4,990 more" in result.stderr
    assert len(result.stderr) < 1000, len(result.stderr)
