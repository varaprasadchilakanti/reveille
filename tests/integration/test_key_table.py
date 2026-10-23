# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Every key the USER_GUIDE's table of equivalent keys names is in that command's JSON.

The table is read from the guide and each command is run, so the guide cannot
name a key a document does not carry.
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_GUIDE = Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md"


def _table() -> list[tuple[str, str, str]]:
    """(fact, command, key) for every cell that names a key."""
    text = _GUIDE.read_text(encoding="utf-8")
    start = text.index("| Fact | `generate`")
    rows = list(
        itertools.takewhile(lambda line: line.strip().startswith("|"), text[start:].splitlines())
    )
    header = [cell.strip(" `") for cell in rows[0].strip().strip("|").split("|")]
    cells = []
    for row in rows[2:]:
        values = [cell.strip() for cell in row.strip().strip("|").split("|")]
        for command, value in zip(header[1:], values[1:], strict=True):
            for key in re.findall(r"`([^`]+)`", value):
                cells.append((values[0], command, key))
    return cells


@pytest.fixture(scope="module")
def documents(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("keys") / "ws"
    repo = root / "r"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
    )
    runs = {
        "generate": ["generate", "--repo", str(repo), "--format", "json", "-o", "-", "-q"],
        "summary": ["summary", "--repo", str(repo), "--format", "json"],
        "state": ["state", "--repo", str(repo), "--format", "json"],
        "brief": ["brief", "--repo", str(repo), "--format", "json", "--since", "2000-01-01"],
        "who-changed": ["who-changed", "a.txt", "--repo", str(repo), "--format", "json"],
        "repos": ["repos", str(root), "--format", "json"],
    }
    out = {}
    for command, args in runs.items():
        result = CliRunner().invoke(app, args)
        assert result.exit_code == ExitCode.SUCCESS, (command, result.stderr)
        out[command] = json.loads(result.stdout)
    return out


def _has(document: Any, key: str) -> bool:
    head, _, rest = key.partition(".")
    if head.endswith("[]"):
        items = document.get(head[:-2]) if isinstance(document, dict) else None
        return bool(items) and all(_has(item, rest) if rest else True for item in items)
    if not isinstance(document, dict) or head not in document:
        return False
    return _has(document[head], rest) if rest else True


def test_the_table_names_keys_for_every_command() -> None:
    assert {command for _, command, _ in _table()} == {
        "generate",
        "summary",
        "state",
        "brief",
        "who-changed",
        "repos",
    }
    assert len(_table()) >= 25


@pytest.mark.parametrize(("fact", "command", "key"), _table())
def test_each_key_is_in_its_document(
    documents: dict[str, Any], fact: str, command: str, key: str
) -> None:
    assert _has(documents[command], key), f"{fact}: {command} has no {key}"
