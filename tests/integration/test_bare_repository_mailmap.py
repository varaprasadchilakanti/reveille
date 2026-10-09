"""A bare repository's identities resolve through the `.mailmap` committed at HEAD.

A bare repository has no working tree, so there is no `.mailmap` file to
read; Git reads the blob at `HEAD:.mailmap` instead. Reveille read only the
file, so one person with an old and a new address was two rows in a bare
clone and one in its working-tree original, while `git shortlog` said one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


def _git(repo: Path, *args: str, email: str = "new@e.test") -> None:
    subprocess.run(
        ["git", "-c", "user.name=Ana", "-c", f"user.email={email}", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _origin(path: Path, mailmap: str) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "old address", email="old@e.test")
    (path / ".mailmap").write_text(mailmap, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "new address")
    return path


def _authors(repo: Path) -> int:
    result = CliRunner().invoke(app, ["summary", "--repo", str(repo), "--format", "json"])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return int(json.loads(result.stdout)["totals"]["authors"])


def _bare(origin: Path, target: Path) -> Path:
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(target)], check=True)
    return target


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.mark.integration
def test_the_bare_clone_counts_one_person_as_its_original_does(tmp_path: Path) -> None:
    origin = _origin(tmp_path / "origin", "Ana <new@e.test> <old@e.test>\n")
    bare = _bare(origin, tmp_path / "bare.git")

    assert _authors(origin) == 1
    assert _authors(bare) == 1


@pytest.mark.integration
def test_an_oversized_committed_mailmap_is_ignored_not_read(tmp_path: Path) -> None:
    """A committed blob is attacker-sized: past the bound it is not read."""
    padding = "# " + "x" * 1_100_000 + "\n"
    origin = _origin(tmp_path / "origin", padding + "Ana <new@e.test> <old@e.test>\n")
    bare = _bare(origin, tmp_path / "bare.git")

    assert _authors(bare) == 2
