# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0
"""Every command runs to the end with Python's sockets refused; Git child processes are out of scope."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


class NetworkCallError(AssertionError):
    """Raised by every refused socket call."""


_ATTEMPTS: list[str] = []


def _refuse(*_args: object, **_kwargs: object) -> None:
    _ATTEMPTS.append("socket")
    raise NetworkCallError("a network call was attempted")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _ATTEMPTS.clear()
    for name in ("connect", "connect_ex", "send", "sendall", "sendto"):
        monkeypatch.setattr(socket.socket, name, _refuse)
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, _refuse)


# One more copy of the helper the TODO in tests/conftest.py would share.
def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "A",
        "GIT_AUTHOR_EMAIL": "a@e.test",
        "GIT_COMMITTER_NAME": "A",
        "GIT_COMMITTER_EMAIL": "a@e.test",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    (path / "src").mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    for n in range(3):
        (path / "src" / "a.py").write_text(f"{n}\n", encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", f"c{n}")
        if n == 0:
            _git(path, "tag", "v1")
    return path


def test_the_refusal_fires(no_network: None) -> None:
    with pytest.raises(NetworkCallError):
        socket.create_connection(("127.0.0.1", 9))


@pytest.mark.parametrize(
    "argv",
    [
        ["generate", "-o", "{out}/report.html"],
        ["generate", "--format", "json", "-o", "{out}/report.json"],
        ["generate", "--format", "csv", "-o", "{out}/report.csv"],
        ["summary", "--format", "json"],
        ["state", "--format", "json"],
        ["brief", "--format", "json"],
        ["who-changed", "src", "--format", "json"],
        ["repos", "{parent}", "--format", "json"],
        ["validate"],
        ["init", "-o", "{out}/reveille.toml"],
        ["capabilities", "--format", "json"],
        ["skill"],
        ["help"],
    ],
    ids=lambda argv: " ".join(argv[:3]),
)
def test_a_command_runs_without_the_network(
    argv: list[str], repo: Path, tmp_path: Path, no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    out = tmp_path / "out"
    out.mkdir()
    args = [a.format(out=out, parent=repo.parent) for a in argv]

    result = CliRunner().invoke(app, args)

    assert not _ATTEMPTS, f"{' '.join(argv)} attempted a network call"
    assert result.exit_code == ExitCode.SUCCESS, f"{' '.join(argv)}: {result.output}"
