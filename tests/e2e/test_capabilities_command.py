# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`capabilities --command <name>`: one command's contract, small enough to read first."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.e2e


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, ["capabilities", *args])
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.parametrize(
    ("name", "bound"),
    [
        ("state", 4096),
        ("brief", 4096),
        ("summary", 4096),
        ("who-changed", 4096),
        ("generate", 8192),
    ],
)
def test_one_command_is_small(name: str, bound: int) -> None:
    code, out, err = _run("--command", name, "--format", "json")

    assert code == ExitCode.SUCCESS, err
    assert len(out.encode()) < bound
    document = json.loads(out)
    assert document["command"]["name"] == name
    assert document["command"]["options"]
    assert [e["code"] for e in document["exit_codes"]] == [0, 1, 2]


def test_it_carries_what_the_command_does() -> None:
    _, out, _ = _run("--command", "brief", "--format", "json")

    assert "latest tag" in json.loads(out)["command"]["description"]


def test_text_names_the_options() -> None:
    code, out, _ = _run("--command", "state")

    assert code == ExitCode.SUCCESS
    assert "--limit" in out and "--format" in out


def test_an_unknown_command_lists_the_known_ones() -> None:
    code, out, err = _run("--command", "nope", "--format", "json")

    assert code == ExitCode.CANNOT_RUN
    assert out == ""
    assert "state" in json.loads(err)["message"]


def test_generate_is_described_as_the_report_not_one_chart() -> None:
    _, out, _ = _run("--command", "generate", "--format", "json")
    command = json.loads(out)["command"]

    assert command["description"] == command["summary"]
    assert "calendar" not in command["description"].lower()
