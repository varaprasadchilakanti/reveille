# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Every command `reveille skill` tells an agent to run runs, and says what it claims.

An instruction file is executed, not read: an agent runs each command as written.
A command in it that fails, or a field it names that is absent, is a defect an
agent meets before any person does.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.agent_guide import GUIDE
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "A",
        "GIT_AUTHOR_EMAIL": "a@e.test",
        "GIT_COMMITTER_NAME": "A",
        "GIT_COMMITTER_EMAIL": "a@e.test",
    }
    done = subprocess.run(
        ["git", *args], cwd=repo, check=True, env=env, capture_output=True, text=True
    )
    return done.stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("guide") / "r"
    (path / "src").mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    for n in range(3):
        (path / "src" / "a.py").write_text(f"{n}\n", encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", f"c{n}")
        if n == 0:
            _git(path, "tag", "v1")
    return path


def _commands() -> list[str]:
    return [span for span in re.findall(r"`([^`]+)`", GUIDE) if span.startswith("reveille ")]


def test_the_guide_names_the_commands_it_should() -> None:
    names = {shlex.split(command)[1] for command in _commands()}

    assert names == {"state", "brief", "who-changed", "summary", "capabilities"}


def test_every_command_in_the_guide_runs(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    values = {
        "<commit>": _git(repo, "rev-parse", "HEAD~1"),
        "<path>": "src",
        "<name>": "state",
        "<date>": "2000-01-01",
    }
    documents = {}
    for command in _commands():
        argv = [values.get(word, word) for word in shlex.split(command)[1:]]
        result = CliRunner().invoke(app, argv)
        assert result.exit_code == ExitCode.SUCCESS, f"{command}: {result.output}"
        documents[command] = json.loads(result.stdout)

    since_commit = documents["reveille brief --from <commit> --format json"]
    assert since_commit["analysed_commit"] == _git(repo, "rev-parse", "HEAD")
    assert documents["reveille brief --format json"]["point"]["from"] == "v1"
    described = documents["reveille capabilities --command <name> --format json"]["command"]
    assert "repository_text" in described

    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", GUIDE))
    keys = {key for document in documents.values() for key in _keys(document)}
    assert "analysed_commit" in named, "positive control: the guide names a field"
    assert named <= keys, f"the guide names fields no command prints: {sorted(named - keys)}"


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_brief_without_a_tag_fails_as_the_guide_says(tmp_path: Path) -> None:
    path = tmp_path / "untagged"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.py").write_text("a\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "c")
    where = ["--repo", str(path), "--format", "json"]

    assert "It exits 2 when the branch has no tag" in " ".join(GUIDE.split())
    without = CliRunner().invoke(app, ["brief", *where])
    assert without.exit_code == ExitCode.CANNOT_RUN
    assert CliRunner().invoke(app, ["brief", "--since", "2000-01-01", *where]).exit_code == 0


def test_the_skill_file_has_the_frontmatter_an_agent_loads() -> None:
    result = CliRunner().invoke(app, ["skill", "--format", "skill"])

    assert result.exit_code == ExitCode.SUCCESS
    head, _, body = result.stdout.partition("\n---\n")
    lines = head.splitlines()
    assert lines[0] == "---" and lines[1] == "name: reveille"
    assert json.loads(lines[2].removeprefix("description: "))
    assert GUIDE in body


def test_the_default_is_the_section_alone() -> None:
    result = CliRunner().invoke(app, ["skill"])

    assert result.exit_code == ExitCode.SUCCESS
    assert result.stdout == GUIDE
