# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""One pass gives each area the date a lookup per area gave.

`brief` asks when each of up to 50 areas last changed before its point. It ran
one `git log -1 -- <area>` each, which walked the history 50 times: 28 seconds
on a 100,000-commit repository. The single pass must answer exactly as the
per-area lookup did, renames, deletions and deep paths included.
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader

pytestmark = pytest.mark.integration

_AREAS = ["src", "src/a", "src/a/deep", "docs", "old", "new", "gone", "never", "(root)"]


def _commit(repo: Path, day: int, message: str) -> None:
    stamp = f"2026-03-{day:02d}T10:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "A",
        "GIT_AUTHOR_EMAIL": "a@e.test",
        "GIT_COMMITTER_NAME": "A",
        "GIT_COMMITTER_EMAIL": "a@e.test",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True, env=env)


def _write(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("areas") / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    _write(path, "README", "r\n")
    _write(path, "src/a/deep/x.py", "x\n")
    _write(path, "old/moved.txt", "m\n" * 20)
    _write(path, "gone/doomed.txt", "d\n")
    _commit(path, 1, "base")
    _write(path, "docs/guide.md", "g\n")
    _commit(path, 3, "docs")
    (path / "new").mkdir()
    subprocess.run(["git", "mv", "old/moved.txt", "new/moved.txt"], cwd=path, check=True)
    _commit(path, 5, "rename out of old into new")
    (path / "gone" / "doomed.txt").unlink()
    _commit(path, 7, "delete")
    _write(path, "src/a/deep/x.py", "y\n")
    _commit(path, 9, "deep change")
    _write(path, "src/b.py", "b\n")
    _commit(path, 11, "src change")
    return path


def _per_area(repo: Path, area: str, before: str) -> datetime.date | None:
    """What the per-area lookup gave: `git log -1` limited to the area."""
    if area == "(root)":
        return None
    out = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--no-merges",
            "--format=%ct",
            f"--before={before}",
            "main",
            "--",
            f":(literal){area}",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return datetime.datetime.fromtimestamp(int(out), tz=datetime.UTC).date() if out else None


@pytest.mark.parametrize("day", [2, 4, 6, 8, 10, 12])
def test_one_pass_agrees_with_a_lookup_per_area_by_date(repo: Path, day: int) -> None:
    before = datetime.date(2026, 3, day)

    answer = GitReader(repo).last_changes_before(_AREAS, None, None, before)

    expected = {a: _per_area(repo, a, f"{before.isoformat()}T00:00:00+00:00") for a in _AREAS}
    assert answer == expected


def test_one_pass_agrees_from_a_commit(repo: Path) -> None:
    point = subprocess.run(
        ["git", "rev-parse", "HEAD~2"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    answer = GitReader(repo).last_changes_before(_AREAS, None, point, None)

    assert answer["gone"] == datetime.date(2026, 3, 7)
    assert answer["src/a/deep"] == datetime.date(2026, 3, 1)
    assert answer["new"] == answer["old"] == datetime.date(2026, 3, 5)
    assert answer["never"] is None and answer["(root)"] is None
