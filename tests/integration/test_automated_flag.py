# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Each contributor row says whether it is an automated account (schema 1.3).

`derived.automated_accounts` counted them; a consumer could not tell which rows.
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

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("bots") / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    for n, (name, email) in enumerate(
        [
            ("Ana", "ana@e.test"),
            ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
        ]
    ):
        (path / f"f{n}").write_text("x", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "C",
            "GIT_COMMITTER_EMAIL": "c@e.test",
        }
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{n}"], cwd=path, check=True, env=env)
    return path


def _out(repo: Path, fmt: str, *flags: str) -> str:
    result = CliRunner().invoke(
        app, ["generate", "--repo", str(repo), "--format", fmt, "-o", "-", "-q", *flags]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return result.stdout


@pytest.mark.parametrize("flags", [(), ("--ranking",), ("--hide-emails",)])
def test_json_rows_say_which_is_automated(repo: Path, flags: tuple[str, ...]) -> None:
    document = json.loads(_out(repo, "json", *flags))

    flagged = {c["name"]: c["automated"] for c in document["contributors"]}
    assert flagged == {"Ana": False, "dependabot[bot]": True}
    assert document["schema_version"] == "1.3"
    assert document["derived"]["automated_accounts"] == sum(flagged.values())


@pytest.mark.parametrize("flags", [(), ("--ranking",)])
def test_csv_rows_say_which_is_automated_in_the_last_column(
    repo: Path, flags: tuple[str, ...]
) -> None:
    rows = list(csv.DictReader(io.StringIO(_out(repo, "csv", *flags).lstrip("﻿"))))

    assert {r["name"]: r["automated"] for r in rows} == {"Ana": "false", "dependabot[bot]": "true"}
    assert list(rows[0])[-1] == "automated"
