# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`capabilities` names every JSON field that carries text from the repository.

Anyone who can commit chooses names, addresses, paths, and branch and tag names,
and a model reading Reveille's JSON should take them as data, never as
instructions. That needs to know where they are. Every input a repository
controls is marked here with "zz"; a marked string at a path the capability
document does not list is a field an agent would trust without being told not to.
Each agent document also says which Reveille wrote it, and from which commit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from reveille import __version__
from reveille.capabilities import REPOSITORY_TEXT
from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_MARK = "zz"


def _git(repo: Path, *args: str, name: str = "ZzAuthor", email: str = "zzmail@zz.test") -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    done = subprocess.run(
        ["git", *args], cwd=repo, check=True, env=env, capture_output=True, text=True
    )
    return done.stdout.strip()


@pytest.fixture(scope="module")
def marked(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository whose every repository-controlled input carries the mark."""
    root = tmp_path_factory.mktemp("marked")
    repo = root / "zzdir"
    (repo / "zzarea" / "zzsub").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "zzbranch")
    _git(repo, "remote", "add", "origin", "https://zzhost.test/zzorg/zzrepo.git")
    (repo / "zzarea" / "zzsub" / "zzfile.zzext").write_text("a\n", encoding="utf-8")
    (repo / "zzgone.zzext").write_text("g\n", encoding="utf-8")
    (repo / "zzmoved.zzext").write_text("m\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c1", "--trailer", "Co-authored-by: ZzCo <zzco@zz.test>")
    _git(repo, "tag", "zztag")
    (repo / "zzother.zzext").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c2", name="zzbot[bot]", email="zzbot@zz.test")
    (repo / "zzarea" / "zzsub" / "zzfile.zzext").write_text("a\nc\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "c3")
    _git(repo, "worktree", "add", "-q", str(root / "zzworktree"), "-b", "zzwtbranch")
    # The working tree: staged, modified, deleted, renamed, untracked, a filter.
    (repo / ".gitattributes").write_text("*.zzfilt filter=zzfilter\n", encoding="utf-8")
    _git(repo, "config", "filter.zzfilter.clean", "cat")
    (repo / "zzstaged.zzext").write_text("s\n", encoding="utf-8")
    _git(repo, "add", "zzstaged.zzext")
    (repo / "zzother.zzext").write_text("b\nm\n", encoding="utf-8")
    (repo / "zzgone.zzext").unlink()
    _git(repo, "mv", "zzmoved.zzext", "zzrenamed.zzext")
    (repo / "zzuntracked.zzext").write_text("u\n", encoding="utf-8")
    return repo


def _json(*args: str) -> dict[str, Any]:
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.output
    document: dict[str, Any] = json.loads(result.stdout)
    return document


def _marked_paths(value: Any, path: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _marked_paths(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for item in value:
            yield from _marked_paths(item, f"{path}[]")
    elif isinstance(value, str) and _MARK in value.lower():
        yield path


def _documents(repo: Path) -> dict[str, dict[str, Any]]:
    where = str(repo)
    return {
        "summary": _json("summary", "--repo", where),
        "state": _json("state", "--repo", where),
        "brief": _json("brief", "--repo", where, "--from", "zztag"),
        "who-changed": _json("who-changed", "zzarea", "--repo", where),
        "repos": _json("repos", str(repo.parent)),
        "generate": _json("generate", "--repo", where, "--area-authors", "--output", "-"),
    }


def test_every_repository_string_is_at_a_listed_path(marked: Path) -> None:
    for command, document in _documents(marked).items():
        found = set(_marked_paths(document))
        assert found, f"positive control: {command} carries no marked text"
        unlisted = found - set(REPOSITORY_TEXT[command])
        assert not unlisted, f"{command} carries repository text at unlisted {sorted(unlisted)}"


def test_capabilities_carry_the_lists(marked: Path) -> None:
    for command, paths in REPOSITORY_TEXT.items():
        described = _json("capabilities", "--command", command)["command"]
        assert described["repository_text"] == list(paths)


def test_each_agent_document_names_its_tool_and_commit(marked: Path) -> None:
    head = _git(marked, "rev-parse", "HEAD")
    documents = _documents(marked)

    for command in ("summary", "state", "brief", "who-changed", "repos"):
        assert documents[command]["reveille_version"] == __version__, command
    assert documents["who-changed"]["analysed_commit"] == head
    assert documents["brief"]["analysed_commit"] == head
    assert documents["state"]["head"] == head
    assert documents["summary"]["repository"]["head_sha"] == head
    assert re.fullmatch(r"[0-9a-f]{40}", head)
