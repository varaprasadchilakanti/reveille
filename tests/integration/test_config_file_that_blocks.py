# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A `reveille.toml` that would block, or never end, is refused, not read.

The file is found in the current directory, so a cloned repository can supply
it: as a link to `/dev/zero` it grew memory without limit, as a named pipe it
waited for ever, and nested deeply it stopped the parser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_CHILD = "import sys; from reveille.cli import app; sys.argv = ['reveille', *sys.argv[1:]]; app()"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=path,
        check=True,
    )
    return path


def _generate(repo: Path, *extra: str) -> subprocess.CompletedProcess[str] | None:
    """Run `generate` where the config is found; None if it had to be killed."""
    try:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                _CHILD,
                "generate",
                "--output",
                str(repo / "r.html"),
                "-q",
                *extra,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes and /dev/zero are POSIX")
@pytest.mark.parametrize("kind", ["pipe", "device"])
def test_a_config_that_is_not_a_regular_file_is_refused(repo: Path, kind: str) -> None:
    """A discovered link is refused as a link, so `/dev/zero` is given with `--config`."""
    config = repo / "reveille.toml"
    if kind == "pipe":
        os.mkfifo(config)
        done = _generate(repo)
    else:
        config.symlink_to("/dev/zero")
        done = _generate(repo, "--config", str(config))

    assert done is not None, "Reveille waited on it"
    assert done.returncode == 2, done.stderr
    assert "not a regular file" in done.stderr, done.stderr


def test_a_config_larger_than_any_a_person_writes_is_refused(repo: Path) -> None:
    (repo / "reveille.toml").write_text(f'[report]\ntitle = "{"x" * (1 << 20)}"\n', "utf-8")

    done = _generate(repo)

    assert done is not None and done.returncode == 2, done
    assert "larger than" in done.stderr, done.stderr
    assert not (repo / "r.html").exists()


def test_a_config_nested_too_deeply_is_a_configuration_error(repo: Path) -> None:
    (repo / "reveille.toml").write_text("x = " + "[" * 5000 + "]" * 5000 + "\n", "utf-8")

    done = _generate(repo)

    assert done is not None and done.returncode == 2, done
    assert "nested" in done.stderr and "defect" not in done.stderr, done.stderr


def test_an_ordinary_config_is_still_read(repo: Path) -> None:
    (repo / "reveille.toml").write_text('[report]\ntitle = "Mine"\n', "utf-8")

    done = _generate(repo)

    assert done is not None and done.returncode == 0, done
    assert "Mine" in (repo / "r.html").read_text(encoding="utf-8")
