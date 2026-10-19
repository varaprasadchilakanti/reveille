# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Under `--format json`, a usage error is a JSON line, like every other message.

An agent that asked for JSON parses stderr as JSON lines. Click's boxed text
for an unknown option or an out-of-range value broke that, on exactly the
mistake an agent is most likely to make.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.parametrize(
    "command", ["summary", "brief", "state", "repos", "who-changed", "capabilities"]
)
def test_an_unknown_option_is_one_json_error(command: str) -> None:
    code, out, err = _run(command, "--format", "json", "--no-such-option")

    assert code == ExitCode.CANNOT_RUN, err
    assert out == ""
    lines = err.splitlines()
    assert len(lines) == 1, err
    message = json.loads(lines[0])
    assert message["level"] == "error"
    assert "No such option: --no-such-option" in message["message"]
    assert f"capabilities --command {command} --format json" in message["message"]


@pytest.mark.parametrize(
    "args",
    [
        ("repos", ".", "--days", "0", "--format", "json"),
        ("who-changed", "--format=json"),
        ("summary", "--limit", "x", "--format", "json"),
    ],
)
def test_a_bad_value_or_a_missing_argument_is_json_too(args: tuple[str, ...]) -> None:
    code, _, err = _run(*args)

    assert code == ExitCode.CANNOT_RUN, err
    assert json.loads(err)["level"] == "error", err


@pytest.mark.parametrize(
    "args",
    [
        ("summary", "--no-such-option"),
        ("summary", "--format", "json", "--format", "text", "--no-such-option"),
        ("summary", "--no-such-option", "--", "--format", "json"),
        # generate writes a JSON file; its stderr is text whatever the format.
        ("generate", "--format", "json", "--no-such-option"),
    ],
)
def test_text_is_kept_where_json_was_not_asked_for(args: tuple[str, ...]) -> None:
    code, _, err = _run(*args)

    assert code == ExitCode.CANNOT_RUN, err
    assert "No such option" in err
    assert not err.lstrip().startswith("{"), err
