# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A file path cannot reorder what the report shows: direction controls appear as escapes.

`invoice<U+202E>fdp.exe` reads as `invoiceexe.pdf` where the control is obeyed. Names
lose such characters when read; a path keeps them, since it names a file, and the
report shows each as `\\u202e`, as the text formats do.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reveille.cli import ExitCode, app

pytestmark = pytest.mark.integration

_CONTROLS = re.compile("[؜‎‏‪-‮⁦-⁩]")


def test_a_paths_direction_controls_are_shown_not_obeyed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name in ("invoice‮fdp.exe", "a⁧b.txt"):
        (repo / name).write_text("x\n" * 50, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", "commit", "-qm", "a"],
        cwd=repo,
        check=True,
    )
    out = repo / "report.html"

    result = CliRunner().invoke(app, ["generate", "--repo", str(repo), "--output", str(out)])

    assert result.exit_code == ExitCode.SUCCESS, result.output
    page = out.read_text(encoding="utf-8")
    spec = re.search(r'id="spec-hotspots">\s*(.*?)\s*</script>', page, re.S)
    assert spec, "positive control: the hotspot chart is in the page"
    labels = json.dumps(json.loads(spec.group(1)), ensure_ascii=False)
    assert "invoice\\\\u202efdp.exe" in labels, "the control is shown as an escape"
    assert not _CONTROLS.search(labels), "a chart label obeys a direction control"
    assert not _CONTROLS.search(page.replace(_bundle(), "")), "the markup carries one"


def _bundle() -> str:
    from reveille.adapters import renderer

    return renderer._vendored("plotly-cartesian.min.js")
