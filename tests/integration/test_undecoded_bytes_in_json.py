# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A path that is not UTF-8 reaches JSON as `\\xNN`, which a strict parser accepts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="needs a file system that keeps any byte"),
]


def _no_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return not any("\ud800" <= ch <= "\udfff" for ch in value)
    if isinstance(value, dict):
        return all(_no_surrogate(k) and _no_surrogate(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_no_surrogate(v) for v in value)
    return True


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "f").write_text("f\n", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "f"],
        cwd=tmp_path,
        check=True,
    )
    with open(os.path.join(os.fsencode(tmp_path), b"new\xfe.txt"), "w", encoding="utf-8") as f:
        f.write("u\n")
    return tmp_path


def test_state_json_writes_the_byte_as_text_does(repo: Path) -> None:
    result = CliRunner().invoke(app, ["state", "--repo", str(repo), "--format", "json"])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert "\\udc" not in result.stdout
    document = json.loads(result.stdout)
    assert document["untracked"]["list"] == ["new\\xfe.txt"]
    assert _no_surrogate(document)

    text = CliRunner().invoke(app, ["state", "--repo", str(repo)])
    assert "Untracked: new\\xfe.txt." in text.stdout


def test_repos_and_who_changed_json_write_the_byte_as_text_does(tmp_path: Path) -> None:
    base = os.fsencode(tmp_path)
    inner = Path(os.fsdecode(os.path.join(base, b"r\xfe")))
    inner.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=inner, check=True)
    path = os.fsdecode(b"caf\xff.txt")
    Path(inner, path).write_text("u\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=inner, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "f"],
        cwd=inner,
        check=True,
    )

    repos = CliRunner().invoke(app, ["repos", str(tmp_path), "--format", "json"])
    changed = CliRunner().invoke(
        app, ["who-changed", path, "--repo", str(inner), "--format", "json"]
    )

    assert repos.exit_code == changed.exit_code == ExitCode.SUCCESS, repos.stderr + changed.stderr
    assert [row["path"] for row in json.loads(repos.stdout)["repositories"]] == ["r\\xfe"]
    assert json.loads(changed.stdout)["path"] == "caf\\xff.txt"
    assert "\\udc" not in repos.stdout + changed.stdout
