# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A file name shaped like a commit's header line does not redate a directory.

A path may hold any byte but NUL, so one spelled as the header `brief` reads
for each commit (`\\x01<hash> <time>`) would set the date of every path after
it in that commit: a directory changed today read as last changed years ago,
and so as "active again".
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path

import pytest

from reveille.adapters.git_reader import GitReader

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name == "nt", reason="a file name holding U+0001"),
]

_OLD = 1_577_880_000  # 2020-01-01T12:00:00Z
_NEW = "2026-03-01T12:00:00+00:00"


def _commit(repo: Path, stamp: str, message: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", message],
        cwd=repo,
        check=True,
        env=env,
    )


def test_a_forged_header_in_a_path_changes_no_date(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "y").write_text("1", encoding="utf-8")
    _commit(tmp_path, f"@{_OLD} +0000", "old")
    # Paths are listed in byte order: the space sorts first, so the forgery is not
    # the commit's first path, and "b/y" follows it.
    (tmp_path / f"{chr(1)} first").write_text("x", encoding="utf-8")
    (tmp_path / f"{chr(1)}{'a' * 40} {_OLD}").write_text("x", encoding="utf-8")
    (tmp_path / "b" / "y").write_text("2", encoding="utf-8")
    _commit(tmp_path, _NEW, "new")

    found = GitReader(tmp_path).last_changes_before(["b"], None, None, None)

    assert found == {"b": datetime.date(2026, 3, 1)}
