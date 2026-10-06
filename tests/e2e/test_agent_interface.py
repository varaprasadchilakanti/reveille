"""The interface an assistant uses (ADR 0015).

An assistant's stdout is its input: anything on it besides the document it
asked for -- a progress line, a "Report written to" -- is a parse error or
a polluted context.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("agent_repo")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for day, (name, email, file) in enumerate(
        [
            ("Zoe", "zoe@e.test", "src/core/a.py"),
            ("Amir", "amir@e.test", "src/core/b.py"),
            ("Zoe", "zoe@e.test", "docs/x.md"),
            ("dependabot[bot]", "bot@e.test", "src/core/a.py"),
        ],
        start=1,
    ):
        target = path / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{day}\n", encoding="utf-8")
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
    """Run from an empty directory: if `-o -` were ever taken as a file name
    again, the file lands there rather than in the working tree."""
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.e2e
class TestOutputToStdout:
    def test_json_is_the_only_thing_on_stdout(self, repo: Path, tmp_path: Path) -> None:
        code, out, err = _run(
            "generate", "--repo", str(repo), "--format", "json", "--deterministic", "-o", "-"
        )

        assert code == ExitCode.SUCCESS, err
        assert json.loads(out)["metadata"]["total_commits"] == 4
        assert "Report written to" not in out
        assert not list(tmp_path.iterdir()), "no file is written"

    def test_csv_on_stdout_has_no_byte_order_mark(self, repo: Path) -> None:
        code, out, _ = _run("generate", "--repo", str(repo), "--format", "csv", "-o", "-")

        assert code == ExitCode.SUCCESS
        assert not out.startswith("﻿")
        rows = list(csv.DictReader(io.StringIO(out)))
        assert {r["email"] for r in rows} == {"zoe@e.test", "amir@e.test", "bot@e.test"}

    def test_html_on_stdout(self, repo: Path) -> None:
        code, out, _ = _run("generate", "--repo", str(repo), "-o", "-")

        assert code == ExitCode.SUCCESS
        assert out.lstrip().lower().startswith("<!doctype html>")


@pytest.mark.e2e
class TestSummary:
    def test_json_answers_the_repository_questions(self, repo: Path) -> None:
        code, out, err = _run("summary", "--repo", str(repo), "--format", "json", "--deterministic")

        assert code == ExitCode.SUCCESS, err
        document = json.loads(out)
        assert document["document"] == "summary"
        assert document["totals"] == {"commits": 4, "authors": 3, "commits_with_co_authors": 0}
        assert set(document["measures"]) == {
            "gini_coefficient",
            "commit_concentration",
            "longest_quiet_run_days",
            "days_since_last_commit",
        }
        assert "check before relying on it" in document["notice"]

    def test_it_names_nobody(self, repo: Path) -> None:
        for fmt in ("json", "text"):
            _, out, _ = _run("summary", "--repo", str(repo), "--format", fmt)
            for identity in ("Zoe", "Amir", "zoe@", "amir@", "dependabot", "bot@"):
                assert identity not in out, f"{identity!r} in the {fmt} summary"

    def test_it_is_small(self, repo: Path) -> None:
        _, out, _ = _run("summary", "--repo", str(repo), "--format", "json")

        assert len(out.encode()) < 4096

    def test_an_empty_window_is_a_negative_answer(self, repo: Path) -> None:
        code, out, _ = _run("summary", "--repo", str(repo), "--since", "2030-01-01")

        assert code == ExitCode.NEGATIVE
        assert out == ""

    def test_an_unknown_format_cannot_run(self, repo: Path) -> None:
        code, _, err = _run("summary", "--repo", str(repo), "--format", "yaml")

        assert code == ExitCode.CANNOT_RUN
        assert "text or json" in err


@pytest.fixture(scope="module")
def many(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Eight authors on one file, one of them under two addresses, a bot,
    and a co-author; plus one commit elsewhere."""
    path = tmp_path_factory.mktemp("who_repo")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    people = [(f"Person {c}", f"{c.lower()}@e.test") for c in "ABCDEFG"]
    people.append(("Person A", "a.other@e.test"))
    people.append(("renovate[bot]", "bot@e.test"))
    for day, (name, email) in enumerate(people, start=1):
        target = path / "lib" / "core.c"
        target.parent.mkdir(exist_ok=True)
        target.write_text(f"{day}\n", encoding="utf-8")
        message = f"c{day}\n\nCo-authored-by: Helper <helper@e.test>\n" if day == 2 else f"c{day}"
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
        subprocess.run(["git", "commit", "-qm", message], cwd=path, check=True, env=env)
    (path / "other.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Z", "-c", "user.email=z@e.test", "commit", "-qm", "other"],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.e2e
class TestWhoChanged:
    def _json(self, repo: Path, *args: str) -> dict:
        code, out, err = _run("who-changed", *args, "--repo", str(repo), "--format", "json")
        assert code == ExitCode.SUCCESS, err
        return json.loads(out)

    def test_the_facts_for_a_file(self, many: Path) -> None:
        answer = self._json(many, "lib/core.c", "--deterministic")

        assert answer["document"] == "who-changed"
        assert answer["commits"] == 9
        assert answer["last_changed"] == "2026-03-09"
        assert answer["authors"]["total"] == 8
        assert answer["automated_accounts"]["list"] == [
            {"name": "renovate[bot]", "email": "bot@e.test"}
        ]
        assert answer["co_authors"]["list"] == [{"name": "Helper", "email": "helper@e.test"}]

    def test_the_five_most_recent_alphabetically(self, many: Path) -> None:
        answer = self._json(many, "lib")

        assert answer["recently_active"] == [
            "Person A",
            "Person D",
            "Person E",
            "Person F",
            "Person G",
        ]

    def test_no_count_or_date_per_person(self, many: Path) -> None:
        answer = self._json(many, "lib/core.c")

        for key in ("authors", "automated_accounts", "co_authors"):
            for person in answer[key]["list"]:
                assert set(person) == {"name", "email"}

    def test_lists_are_bounded(self, many: Path) -> None:
        answer = self._json(many, "lib", "--limit", "3")

        assert len(answer["authors"]["list"]) == 3
        assert answer["authors"] | {"list": []} == {"total": 8, "truncated": True, "list": []}

    def test_text_tells_one_name_with_two_addresses_apart(self, many: Path) -> None:
        _, out, _ = _run("who-changed", "lib/core.c", "--repo", str(many))

        assert "Person A <a@e.test>" in out
        assert "Person A <a.other@e.test>" in out

    def test_a_path_nobody_changed_is_a_negative_answer(self, many: Path) -> None:
        code, out, err = _run("who-changed", "nowhere.c", "--repo", str(many))

        assert code == ExitCode.NEGATIVE
        assert out == ""
        assert "nowhere.c" in err

    @pytest.mark.parametrize("path", [":(exclude)lib", "--output=x", "*.c"])
    def test_the_path_is_taken_literally(self, many: Path, path: str) -> None:
        code, _, _ = _run("who-changed", "--repo", str(many), "--", path)

        assert code == ExitCode.NEGATIVE, "no file has that literal name"

    def test_a_path_outside_the_repository_cannot_run(self, many: Path, tmp_path: Path) -> None:
        for path in (str(tmp_path), "../elsewhere"):
            code, _, _ = _run("who-changed", path, "--repo", str(many))
            assert code == ExitCode.CANNOT_RUN

    def test_an_absolute_path_inside_the_repository_works(self, many: Path) -> None:
        answer = self._json(many, str(many / "lib" / "core.c"))

        assert answer["path"] == "lib/core.c"


@pytest.mark.e2e
class TestBoundedLists:
    def _json(self, repo: Path, *args: str) -> dict:
        code, out, err = _run("generate", "--repo", str(repo), "--format", "json", "-o", "-", *args)
        assert code == ExitCode.SUCCESS, err
        return json.loads(out)

    def test_a_limit_bounds_the_rows_and_states_the_total(self, many: Path) -> None:
        payload = self._json(many, "--limit", "2")

        assert len(payload["contributors"]) == 2
        assert payload["contributors_total"] == 10
        assert payload["contributors_truncated"] is True
        assert payload["provenance"]["limit"] == 2

    def test_without_a_limit_every_row_is_there(self, many: Path) -> None:
        payload = self._json(many)

        assert len(payload["contributors"]) == payload["contributors_total"] == 10
        assert payload["contributors_truncated"] is False

    def test_area_names_are_bounded_too(self, many: Path) -> None:
        payload = self._json(many, "--limit", "2", "--area-authors")
        (lib,) = [a for a in payload["areas"] if a["area"] == "lib"]

        assert len(lib["listed_authors"]) == 2
        assert lib["listed_authors_truncated"] is True

    def test_csv_rows_are_bounded(self, many: Path) -> None:
        code, out, _ = _run(
            "generate", "--repo", str(many), "--format", "csv", "-o", "-", "--limit", "3"
        )

        assert code == ExitCode.SUCCESS
        assert len(list(csv.DictReader(io.StringIO(out)))) == 3
