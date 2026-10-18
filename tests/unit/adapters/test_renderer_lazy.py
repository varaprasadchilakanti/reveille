# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Only an HTML report reads the Plotly bundle and compiles the template.

Read at import, the 4.8 MB bundle cost every command, `state` and `brief`
included, about 14 MB and its read time.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from reveille.adapters import renderer
from reveille.adapters.renderer import Renderer
from tests.unit.adapters.test_lorenz_chart import _report_data

pytestmark = pytest.mark.unit


def test_importing_the_renderer_reads_no_bundle() -> None:
    code = (
        "import plotly.offline\n"
        "plotly.offline.get_plotlyjs = lambda: (_ for _ in ()).throw(SystemExit(3))\n"
        "import reveille.services.report\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)

    assert done.returncode == 0, done.stderr


def test_json_and_csv_compile_no_template_and_read_no_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise AssertionError("an HTML-only resource was loaded")

    monkeypatch.setattr(renderer, "_plotly_js_bundle", refuse)
    monkeypatch.setattr(renderer.Environment, "get_template", refuse)
    writer = Renderer()

    writer.render_json(_report_data([3, 1]), tmp_path / "r.json")
    writer.render_csv(_report_data([3, 1]), tmp_path / "r.csv")


def test_html_compiles_the_template_once_per_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compiled: list[str] = []
    real = renderer.Environment.get_template

    def counting(self: object, name: str, *args: object, **kwargs: object) -> object:
        compiled.append(name)
        return real(self, name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(renderer.Environment, "get_template", counting)
    writer = Renderer()
    writer.render(_report_data([3, 1]), tmp_path / "a.html")
    writer.render(_report_data([3, 1]), tmp_path / "b.html")

    assert compiled == ["report.html.j2"]
    assert (tmp_path / "a.html").read_bytes() == (tmp_path / "b.html").read_bytes()
