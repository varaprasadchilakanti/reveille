"""A program a repository's own configuration names is not run by any read.

`log.showSignature=true` in `.git/config` makes every `git log` verify
signatures by running `gpg.program`, which that same file can name. A
repository handed over as a directory carries its `.git/config`. Every read
pins the setting off, so the program never runs.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Ana", "-c", "user.email=ana@e.test", *args],
        cwd=repo,
        check=True,
        input=stdin,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture()
def hostile(tmp_path: Path) -> tuple[Path, Path]:
    """A repository whose head commit carries a signature header, and whose
    configuration asks every log to verify it with a marker-writing script."""
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "ran"
    program = tmp_path / "fake-gpg"
    program.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IEXEC)

    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")
    tree, parent = _git(repo, "write-tree"), _git(repo, "rev-parse", "HEAD")
    signed = (
        f"tree {tree}\nparent {parent}\n"
        "author Ana <ana@e.test> 1700000000 +0000\n"
        "committer Ana <ana@e.test> 1700000000 +0000\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n -----END PGP SIGNATURE-----\n\nsigned\n"
    )
    sha = _git(repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=signed)
    _git(repo, "update-ref", "refs/heads/main", sha)
    _git(repo, "config", "log.showSignature", "true")
    _git(repo, "config", "gpg.program", str(program))

    # Guard the guard: plain Git does run it.
    subprocess.run(["git", "log", "-1"], cwd=repo, capture_output=True, check=False)
    assert marker.exists(), "the fixture does not make git log run the program"
    marker.unlink()
    return repo, marker


@pytest.mark.integration
@pytest.mark.parametrize(
    "command",
    [["generate", "-o", "-"], ["summary"], ["who-changed", "a.txt"], ["validate"]],
    ids=["generate", "summary", "who-changed", "validate"],
)
def test_no_read_runs_the_signature_program(hostile: tuple[Path, Path], command: list[str]) -> None:
    repo, marker = hostile
    result = CliRunner().invoke(
        app,
        [*command, "--repo", str(repo), "--exclude-author", "nobody@e.test"]
        if command[0] != "validate"
        else [*command, "--repo", str(repo)],
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert not marker.exists(), "a program named in the repository's .git/config ran"
