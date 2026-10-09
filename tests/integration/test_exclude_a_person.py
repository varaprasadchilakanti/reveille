"""`--exclude-author` removes a person, not one spelling of their name.

An identity is its address (ADR 0002). Ana commits as "Ana" three times and
as "Ana Silva" once, from one address. Excluding "Ana Silva" removed one
commit and left "Ana" with three, exit 0 and no warning: the one flag whose
purpose is privacy left the person in the report.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("exclude") / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    authors = [("Ana", "ana@e.test")] * 3 + [("Ana Silva", "ana@e.test"), ("Ben", "ben@e.test")]
    for day, (name, email) in enumerate(authors, start=1):
        (path / "shared.txt").write_text(f"{day}\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)
    return path


@pytest.fixture(autouse=True)
def _scratch_cwd(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.integration
@pytest.mark.parametrize("value", ["Ana Silva", "Ana", "ANA@E.TEST"])
def test_any_one_name_or_the_address_removes_every_commit(repo: Path, value: str) -> None:
    code, out, err = _run(
        "generate", "--repo", str(repo), "--format", "json", "--exclude-author", value, "-o", "-"
    )
    assert code == ExitCode.SUCCESS, err
    payload = json.loads(out)

    assert [c["email"] for c in payload["contributors"]] == ["ben@e.test"]
    assert payload["metadata"]["total_commits"] == 1
    assert "ana@e.test" not in out.lower()
    assert "ana silva" not in out.lower()


@pytest.mark.integration
def test_who_changed_leaves_the_person_out_too(repo: Path) -> None:
    code, out, err = _run(
        "who-changed", "shared.txt", "--repo", str(repo), "--exclude-author", "Ana Silva"
    )
    assert code == ExitCode.SUCCESS, err

    assert "Ana" not in out


@pytest.mark.integration
def test_a_value_that_matches_nobody_still_warns(repo: Path) -> None:
    code, _, err = _run("summary", "--repo", str(repo), "--exclude-author", "Nobody", "--verbose")
    assert code == ExitCode.SUCCESS

    assert "matched no commits for: nobody" in err


@pytest.mark.integration
def test_one_person_under_two_names_draws_no_warning(repo: Path) -> None:
    """Ana and Ana Silva share one address: one person, nothing to narrow."""
    _, _, err = _run("summary", "--repo", str(repo), "--exclude-author", "Ana Silva")

    assert "matched 2 addresses" not in err


@pytest.mark.integration
def test_a_name_two_people_share_removes_both_and_says_so(tmp_path: Path) -> None:
    """ADR 0020: the safe direction for a privacy flag, stated, never silent."""
    path = tmp_path / "two"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day, email in enumerate(["alice@x.test", "alice@other.test", "bob@e.test"], start=1):
        (path / "f.txt").write_text(f"{day}\n", encoding="utf-8")
        name = "Bob" if email.startswith("bob") else "Alice"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=path, check=True, env=env)

    code, out, err = _run(
        "summary", "--repo", str(path), "--exclude-author", "Alice", "--format", "json"
    )
    assert code == ExitCode.SUCCESS, err

    assert json.loads(out)["totals"]["commits"] == 1
    assert "matched 2 addresses" in err
    assert "alice@other.test, alice@x.test" in err
