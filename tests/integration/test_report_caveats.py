# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The report says, inside the file, how its figures can mislead.

The documentation does not travel with a report someone forwards, so the rules
that most change a reading are stated in it, with the report's own numbers.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration


def _commit(repo: Path, message: str, *, author_date: str, commit_date: str, email: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": email.split("@")[0],
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "C",
        "GIT_COMMITTER_EMAIL": "c@e.test",
        "GIT_AUTHOR_DATE": author_date,
        "GIT_COMMITTER_DATE": commit_date,
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True, env=env)


def _repo(tmp_path: Path, *, merge: bool = False, mailmap: bool = False) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a").write_text("1\n", encoding="utf-8")
    if mailmap:
        (path / ".mailmap").write_text("Ana <ana@e.test> <ana@old.test>\n", encoding="utf-8")
    stamp = "2026-03-01T10:00:00+00:00"
    _commit(path, "base", author_date=stamp, commit_date=stamp, email="ana@e.test")
    (path / "a").write_text("2\n", encoding="utf-8")
    _commit(
        path,
        "pair\n\nCo-authored-by: Ben <ben@e.test>",
        author_date="2026-03-02T10:00:00+00:00",
        commit_date="2026-03-02T10:00:00+00:00",
        email="ana@e.test",
    )
    if merge:
        subprocess.run(["git", "switch", "-qc", "side", "HEAD~1"], cwd=path, check=True)
        (path / "b").write_text("b\n", encoding="utf-8")
        _commit(path, "side", author_date=stamp, commit_date=stamp, email="sid@e.test")
        subprocess.run(["git", "switch", "-q", "main"], cwd=path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=C",
                "-c",
                "user.email=c@e.test",
                "merge",
                "-q",
                "--no-edit",
                "side",
            ],
            cwd=path,
            check=True,
        )
    return path


def _caveats(repo: Path, tmp_path: Path) -> str:
    out = tmp_path / "report.html"
    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "-o", str(out)])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    match = re.search(r'<aside class="caveats".*?</aside>', out.read_text(encoding="utf-8"), re.S)
    assert match is not None, "the report has no caveats panel"
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(0)).split())


def test_the_panel_states_the_rules_that_change_a_reading(tmp_path: Path) -> None:
    text = _caveats(_repo(tmp_path), tmp_path)

    assert "Commits are counted, not weighed." in text
    assert "not effort, value or anyone's performance" in text
    assert "A squash merge is one commit by one author." in text
    assert "Dates are commit dates." in text
    assert "Concentration is not a bus factor." in text


def test_it_counts_the_merges_left_out(tmp_path: Path) -> None:
    text = _caveats(_repo(tmp_path, merge=True), tmp_path)

    assert "1 merge commit in this branch and period is left out" in text


def test_it_says_when_there_were_no_merges(tmp_path: Path) -> None:
    text = _caveats(_repo(tmp_path), tmp_path)

    assert "This branch and period have none." in text


def test_it_counts_the_commits_carrying_a_co_author_trailer(tmp_path: Path) -> None:
    text = _caveats(_repo(tmp_path), tmp_path)

    assert "which 1 commit here carries" in text


@pytest.mark.parametrize(("mailmap", "expected"), [(True, "merged by the"), (False, "No .mailmap")])
def test_it_says_whether_a_mailmap_merged_identities(
    tmp_path: Path, mailmap: bool, expected: str
) -> None:
    text = _caveats(_repo(tmp_path, mailmap=mailmap), tmp_path)

    assert expected in text


def test_a_commit_is_placed_on_its_commit_date_as_the_panel_says(tmp_path: Path) -> None:
    """What "Dates are commit dates" claims: authored in March, rebased in May, shown in May."""
    repo = tmp_path / "d"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a").write_text("1\n", encoding="utf-8")
    _commit(
        repo,
        "rebased",
        author_date="2026-03-01T10:00:00+00:00",
        commit_date="2026-05-01T10:00:00+00:00",
        email="ana@e.test",
    )

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", "json", "-o", "-", "--deterministic"]
    )

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    assert '"analysis_since": "2026-05-01"' in result.stdout
