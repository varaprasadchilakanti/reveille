# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`--hide-emails`: no address of anyone in the history reaches a shared report.

Every place an address can enter is in the fixture: authors, co-author trailers,
an address written as a name, a bot recognised only by its address, people below
`--min-commits`, area authors and an SSH remote's login.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import plotly.offline
import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_ADDRESSES = (
    "ana@corp.test",
    "ana.other@home.test",
    "ben@corp.test",
    "carol@corp.test",
    "dee@corp.test",
    "ci-bot[bot]@builds.test",
    "jane",  # the SSH login in the remote
)


def _commit(repo: Path, name: str, email: str, message: str, day: int) -> None:
    stamp = f"2026-03-{day:02d}T10:00:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "C",
        "GIT_COMMITTER_EMAIL": "c@e.test",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    (repo / "src" / f"f{day}.txt").write_text(f"{day}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True, env=env)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("hide") / "r"
    (path / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "jane@git.corp.test:team/r.git"], cwd=path, check=True
    )
    day = 1
    for _ in range(3):
        _commit(path, "Ana", "ana@corp.test", "work", day)
        day += 1
    # The same name under a second address: the chart labels must still tell them apart.
    _commit(path, "Ana", "ana.other@home.test", "work", day)
    day += 1
    _commit(path, "Ben", "ben@corp.test", "pair\n\nCo-authored-by: Carol <carol@corp.test>", day)
    day += 1
    _commit(path, "Ben", "ben@corp.test", "more", day)
    day += 1
    # An address written as a name, as an unconfigured Git produces.
    _commit(path, "dee@corp.test", "dee@corp.test", "one", day)
    day += 1
    # A bot recognised only by its address.
    _commit(path, "CI", "ci-bot[bot]@builds.test", "bump", day)
    return path


def _run(repo: Path, *args: str) -> str:
    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "--deterministic", *args])
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


def _leaks(text: str) -> list[str]:
    authored = text.replace(plotly.offline.get_plotlyjs(), "")
    return [address for address in _ADDRESSES if address in authored]


@pytest.mark.parametrize("fmt", ["html", "json", "csv"])
def test_no_address_reaches_the_report(repo: Path, fmt: str) -> None:
    extra = ("--area-authors", "--min-commits", "2") if fmt == "html" else ()
    text = _run(repo, "--hide-emails", "--format", fmt, "-o", "-", *extra)

    assert _leaks(text) == []


def test_the_fixture_does_carry_every_address_without_the_flag(repo: Path) -> None:
    """Positive control: without it, every address the test looks for is there."""
    html = _run(repo, "--format", "html", "-o", "-", "--area-authors", "--min-commits", "2")
    json_text = _run(repo, "--format", "json", "-o", "-")

    assert set(_leaks(html + json_text)) == set(_ADDRESSES)


def test_every_figure_is_unchanged(repo: Path) -> None:
    plain = json.loads(_run(repo, "--format", "json", "-o", "-"))
    hidden = json.loads(_run(repo, "--format", "json", "-o", "-", "--hide-emails"))

    assert hidden["derived"] == plain["derived"]
    assert hidden["metadata"]["total_commits"] == plain["metadata"]["total_commits"]
    strip = ("email", "name")
    assert [{k: v for k, v in c.items() if k not in strip} for c in hidden["contributors"]] == [
        {k: v for k, v in c.items() if k not in strip} for c in plain["contributors"]
    ]


def test_a_bot_known_only_by_its_address_is_still_automated(repo: Path) -> None:
    hidden = json.loads(_run(repo, "--format", "json", "-o", "-", "--hide-emails"))

    assert hidden["derived"]["automated_accounts"] == 1


def test_tokens_are_numbered_in_table_order_and_cannot_receive_mail(repo: Path) -> None:
    hidden = json.loads(_run(repo, "--format", "json", "-o", "-", "--hide-emails"))

    emails = [c["email"] for c in hidden["contributors"]]
    assert emails[0] == "contributor-1@hidden.invalid"
    assert all(e.endswith("@hidden.invalid") for e in emails)
    assert len(set(emails)) == len(emails)


def test_two_people_of_one_name_are_told_apart_by_their_tokens(repo: Path) -> None:
    html = _run(repo, "--hide-emails", "-o", "-")

    assert re.search(r"Ana \(contributor-\d+\)", html)


def test_an_address_written_as_a_name_is_hidden(repo: Path) -> None:
    hidden = json.loads(_run(repo, "--format", "json", "-o", "-", "--hide-emails"))

    assert "(address hidden)" in [c["name"] for c in hidden["contributors"]]


def test_the_remote_keeps_its_host_and_loses_its_login(repo: Path) -> None:
    html = _run(repo, "--hide-emails", "-o", "-")

    assert "git.corp.test:team/r.git" in html
    assert "jane@" not in html


def test_the_report_says_the_addresses_are_hidden(repo: Path) -> None:
    hidden = json.loads(_run(repo, "--format", "json", "-o", "-", "--hide-emails"))

    assert hidden["provenance"]["emails_hidden"] is True


def test_the_same_repository_gives_the_same_tokens(repo: Path) -> None:
    first = _run(repo, "--format", "json", "-o", "-", "--hide-emails")

    assert _run(repo, "--format", "json", "-o", "-", "--hide-emails") == first


def test_the_config_file_turns_it_on(repo: Path, tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text("[report]\nhide_emails = true\n", encoding="utf-8")

    text = _run(repo, "--config", str(config), "--format", "json", "-o", "-")

    assert _leaks(text) == []


def test_the_config_file_refuses_a_quoted_boolean(repo: Path, tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text('[report]\nhide_emails = "false"\n', encoding="utf-8")

    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--config", str(config), "-o", "-"]
    )

    assert result.exit_code == ExitCode.CANNOT_RUN
    assert "hide_emails" in result.stderr
