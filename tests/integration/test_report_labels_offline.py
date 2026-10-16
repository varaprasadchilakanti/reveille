# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""No chart label in a generated report carries markup, whatever the addresses are.

Two contributors sharing a name are told apart by address. Wrapped in angle
brackets, an address such as `span style='background-image:url(...)' x` became
a tag Plotly rendered, and the browser fetched the URL as soon as the report was
opened: the report told a third party when, and from where, it was read.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_EMAILS = [
    "span style='background-image:url(https://evil.example/bg.png)' x",
    "a href='https://evil.example/pwn' x",
    "b x",
    "plain@e.test",
]


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        # Hover and text templates are Reveille's own markup, not repository text.
        return [s for k, v in value.items() if not k.endswith("template") for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_no_chart_string_holds_a_tag(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for day, email in enumerate(_EMAILS, start=1):
        (repo / "f.txt").write_text(f"{day}\n", encoding="utf-8")
        stamp = f"2026-03-{day:02d}T10:00:00+00:00"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Dup",
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "C",
            "GIT_COMMITTER_EMAIL": "c@e.test",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"c{day}"], cwd=repo, check=True, env=env)
    report = tmp_path / "report.html"

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "--output", str(report)])

    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    html = report.read_text(encoding="utf-8")
    specs = re.findall(
        r'<script type="application/json" id="spec-[^"]+">(.*?)</script>', html, re.S
    )
    assert specs, "no chart specifications found"
    strings = [s for spec in specs for s in _strings(json.loads(spec))]
    assert any("plain@e.test" in s for s in strings), "the repeated name lost its address"
    assert not [s for s in strings if "<" in s or ">" in s]
