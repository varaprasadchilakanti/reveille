# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Control and direction characters in a remote, a branch or an address are shown.

Names lose them when read; an address, a branch and a remote keep them, because
they name something real. Obeyed, U+202E reverses what follows on the page and
in a spreadsheet, and an escape sequence reaches a terminal that `cat`s a CSV.
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

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name == "nt", reason="a branch name holding U+202E"),
]

_RLO, _ESC = chr(0x202E), chr(0x1B)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", f"br{_RLO}x"], cwd=path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://e.test/a{_RLO}b{_ESC}[31m.git"],
        cwd=path,
        check=True,
    )
    (path / "f").write_text("f", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=E", "-c", f"user.email=e{_RLO}v@e.test", "commit", "-qm", "c"],
        cwd=path,
        check=True,
    )
    return path


def _report(repo: Path, output_format: str) -> str:
    out = repo.parent / f"r.{output_format}"
    result = CliRunner().invoke(
        app, ["generate", "-q", "-r", str(repo), "--format", output_format, "-o", str(out)]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    return out.read_text(encoding="utf-8")


def test_the_html_report_shows_them_as_escapes(repo: Path) -> None:
    page = _report(repo, "html")
    # The vendored chart bundle holds its own bytes.
    text = re.sub(r"<script\b.*?</script>", "", page, flags=re.DOTALL)
    assert "Remote:" in text and "contributor-email" in text, "positive control"

    assert _RLO not in text and _ESC not in text
    assert "https://e.test/a\\u202eb\\u001b[31m.git" in page
    assert "br\\u202ex" in page and "e\\u202ev@e.test" in page


def test_the_csv_shows_them_as_escapes(repo: Path) -> None:
    sheet = _report(repo, "csv")

    assert _RLO not in sheet and "e\\u202ev@e.test" in sheet


def test_json_keeps_the_value_exact(repo: Path) -> None:
    """JSON escapes them itself, and a reader gets the address back as it is."""
    [person] = json.loads(_report(repo, "json"))["contributors"]

    assert person["email"] == f"e{_RLO}v@e.test"
