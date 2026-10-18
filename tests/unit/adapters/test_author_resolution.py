# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Each author is resolved once per read, not once per commit."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader

pytestmark = pytest.mark.unit


def test_one_author_s_commits_share_their_strings(tmp_path: Path) -> None:
    """One resolution per author: 100,000 commits by 500 people hold 500 names, not 100,000."""
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for n in range(3):
        (path / "a.txt").write_text(str(n), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Ann", "-c", "user.email=ann@e.test", "commit", "-qm", "m"],
            cwd=path,
            check=True,
        )

    first, *rest = GitReader(path).read_commits(None, None, None, [])

    assert rest and all(c.author_name is first.author_name for c in rest)
    assert all(c.author_email is first.author_email for c in rest)
