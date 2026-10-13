# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The commands written for assistants name nobody, in every format they offer.

`state`, `brief` and `summary` are documented as naming no author, so their
output can be sent to a hosted model. The repository below has authors,
committers, a co-author, a `.mailmap` alias and a bot, each with a distinctive
name and address; none may appear. `who-changed` names people by design and is
not here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.e2e

_PEOPLE = [
    ("Zebulon Quixote", "zq@corp.test"),
    ("Philippa Vantablack", "pv@corp.test"),
    ("Marisol Ottoline", "marisol.o@home.test"),
]
_CO_AUTHOR = ("Ignatius Fairweather", "ifair@corp.test")
_ALIAS = ("Z. Quixote Old", "zq.old@corp.test")
_BOT = ("renovate[bot]", "29139614+renovate[bot]@users.noreply.github.com")

_FORBIDDEN = [
    part
    for name, email in [*_PEOPLE, _CO_AUTHOR, _ALIAS, _BOT]
    for part in (name, email, email.split("@")[0], *name.split())
    if len(part) > 3
]


def _commit(repo: Path, who: tuple[str, str], path: str, day: int, message: str = "work") -> None:
    name, email = who
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": f"2026-02-{day:02d}T10:00:00+00:00",
        "GIT_COMMITTER_DATE": f"2026-02-{day:02d}T10:00:00+00:00",
    }
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"{day}\n")
    for args in (["add", "-A"], ["commit", "-qm", message]):
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *args],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
        )


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("people") / "project"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / ".mailmap").write_text(
        f"{_PEOPLE[0][0]} <{_PEOPLE[0][1]}> {_ALIAS[0]} <{_ALIAS[1]}>\n", encoding="utf-8"
    )
    _commit(path, _PEOPLE[0], "src/core/a.py", 1)
    subprocess.run(["git", "-c", "tag.gpgSign=false", "tag", "v1"], cwd=path, check=True)
    _commit(path, _ALIAS, "src/core/a.py", 2)
    _commit(path, _PEOPLE[1], "src/api/b.py", 3)
    _commit(
        path,
        _PEOPLE[2],
        "docs/c.md",
        4,
        f"docs\n\nCo-authored-by: {_CO_AUTHOR[0]} <{_CO_AUTHOR[1]}>",
    )
    _commit(path, _BOT, "package-lock.json", 5)
    (path / "src" / "api" / "b.py").write_text("changed\n", encoding="utf-8")
    return path


_RUNS = [
    (command, fmt)
    for command, formats in [
        (("state",), ("text", "json", "markdown", "line")),
        (("brief",), ("text", "json", "markdown", "line")),
        (("brief", "--from", "v1"), ("text", "json", "markdown", "line")),
        (("summary",), ("text", "json", "markdown")),
    ]
    for fmt in formats
]


@pytest.mark.parametrize(
    ("command", "fmt"), _RUNS, ids=lambda v: "-".join(v) if isinstance(v, tuple) else v
)
def test_no_name_or_address_appears(repo: Path, command: tuple[str, ...], fmt: str) -> None:
    result = CliRunner().invoke(app, [*command, "--repo", str(repo), "--format", fmt])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    output = (result.stdout + result.stderr).lower()
    leaked = [part for part in _FORBIDDEN if part.lower() in output]
    assert leaked == [], f"{' '.join(command)} --format {fmt} named {leaked}"


def test_the_check_would_see_a_name(repo: Path) -> None:
    """Positive control: who-changed names people, and the same check catches it."""
    result = CliRunner().invoke(app, ["who-changed", "src", "--repo", str(repo)])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert any(part.lower() in result.stdout.lower() for part in _FORBIDDEN)
