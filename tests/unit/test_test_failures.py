# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`.github/scripts/test_failures.py` groups CI failures by cause."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "test_failures.py"

_REPORT = """<testsuites><testsuite>
<testcase classname="tests.integration.test_a" name="test_one[x.y]">
  <failure message="OSError: [Errno 22] Invalid argument: 'C:\\Users\\r\\pytest-1\\v\\*.md'"/>
</testcase>
<testcase classname="tests.integration.test_a.TestB" name="test_two">
  <error message="OSError: [Errno 22] Invalid argument: 'C:\\Users\\r\\pytest-7\\w\\*.md'"/>
</testcase>
<testcase classname="tests.integration.test_a" name="test_three">
  <error message="OSError: [Errno 22] Invalid argument: 'C:\\Users\\r\\pytest-9\\w\\*.md'"/>
</testcase>
<testcase classname="tests.unit.test_c" name="test_four">
  <failure message="CalledProcessError: git update-ref 45bcd89e00e55b955dbad086506523dbdda15da2"/>
</testcase>
<testcase classname="" name="::add-mask::x"><failure message=" "/></testcase>
<testcase classname="tests.unit.test_c" name="test_passes"/>
</testsuite></testsuites>"""


def _run(tmp_path: Path, *flags: str) -> str:
    report = tmp_path / "pytest.xml"
    report.write_text(_REPORT, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), str(report), *flags],
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    return done.stdout


def test_one_cause_is_one_line_with_its_count(tmp_path: Path) -> None:
    out = _run(tmp_path)

    assert out.splitlines()[0] == "5 not passed, 4 causes"
    assert "2x error: OSError: [Errno <n>] Invalid argument: '<path>'" in out
    assert "1x failure: CalledProcessError: git update-ref <sha>" in out
    assert "  - test_a::test_one[x.y]" in out
    assert "TestB::test_two" in out
    assert "test_passes" not in out


def test_annotate_prints_the_summary_as_one_annotation(tmp_path: Path) -> None:
    [annotation] = [x for x in _run(tmp_path, "--annotate").splitlines() if x.startswith("::")]

    assert annotation.startswith("::error title=Test failures::5 not passed, 4 causes%0A")


def test_no_line_is_read_as_a_workflow_command(tmp_path: Path) -> None:
    out = _run(tmp_path)

    assert "1x failure: (no message)" in out
    assert not [x for x in out.splitlines() if x.lstrip().startswith("::")]


def test_a_missing_report_is_stated(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), str(tmp_path / "none.xml")],
        capture_output=True,
        check=True,
        encoding="utf-8",
    )

    assert done.stdout.startswith("no test report:")


def test_a_name_outside_the_code_page_is_written(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuite><testcase classname="m" name="t"><failure message="名前"/></testcase></testsuite>',
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), str(report)],
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )

    assert "1x failure: 名前" in done.stdout.decode("utf-8")
