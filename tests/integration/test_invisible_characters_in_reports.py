# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Characters that show as nothing are shown as escapes in the HTML report and the CSV.

Text, Markdown and line output escaped tag characters (U+E0000 to U+E007F), the
zero-width space, the word joiner and U+2028; the report and the CSV, the files
that are passed on, carried them raw in names, addresses and the branch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name == "nt", reason="a branch name holding U+2028"),
]

_TAGS = "".join(chr(0xE0000 + ord(c)) for c in "AB")
_LS, _WJ, _BOM = chr(0x2028), chr(0x2060), chr(0xFEFF)
_HIDDEN = (_TAGS, _LS, _WJ, _BOM)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", f"br{_TAGS}{_LS}x"], cwd=path, check=True)
    (path / "f").write_text("f", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            f"user.name=Ev{_TAGS}{_WJ}x",
            "-c",
            f"user.email=e{_TAGS}{_LS}v{_BOM}@e.test",
            "commit",
            "-qm",
            "c",
        ],
        cwd=path,
        check=True,
    )
    return path


@pytest.mark.parametrize("output_format", ["html", "csv"])
def test_nothing_invisible_is_written(repo: Path, output_format: str) -> None:
    out = repo.parent / f"r.{output_format}"
    result = CliRunner().invoke(
        app, ["generate", "-q", "-r", str(repo), "--format", output_format, "-o", str(out)]
    )
    assert result.exit_code == ExitCode.SUCCESS, result.stderr
    written = out.read_text(encoding="utf-8-sig" if output_format == "csv" else "utf-8")

    found = {hex(ord(c)) for c in written if any(c in hidden for hidden in _HIDDEN)}
    assert not found, f"written raw: {sorted(found)}"
    assert "\\U000e0041\\U000e0042" in written, "positive control: the escape is shown"
