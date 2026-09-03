"""The CLA gate must accept the pull-request template this repository ships.

These tests do not reimplement the check. They extract the script from
`.github/workflows/cla.yml` and run it, so what is asserted is the code that
actually gates contributions.

The defect that motivated them: the acceptance pattern required the tick and
the CLA version on one physical line, while the shipped template wraps that
bullet across three. Every external pull request using the template failed the
gate, and the failure message told the contributor to tick a box they had
already ticked. Nothing tested the gate against the template, so nothing caught
it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "cla.yml"
_TEMPLATE = _ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"


def _gate_script() -> str:
    """The Python heredoc the workflow runs, dedented to column zero."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"python3 - <<'PY'\n(.*?)\n[ \t]*PY\n", text, re.DOTALL)
    assert match is not None, "could not find the gate script in cla.yml"
    lines = match.group(1).split("\n")
    indent = min(len(ln) - len(ln.lstrip()) for ln in lines if ln.strip())
    return "\n".join(ln[indent:] for ln in lines)


def _cla_version() -> str:
    """The CLA version the workflow currently requires."""
    match = re.search(r'CLA_VERSION:\s*"([^"]+)"', _WORKFLOW.read_text(encoding="utf-8"))
    assert match is not None, "could not find CLA_VERSION in cla.yml"
    return match.group(1)


def _run_gate(body: str) -> int:
    """Run the shipped gate against a pull-request body; return its exit code."""
    return subprocess.run(
        [sys.executable, "-c", _gate_script()],
        env={"PR_BODY": body, "CLA_VERSION": _cla_version(), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    ).returncode


@pytest.mark.unit
class TestClaGateAcceptsTheShippedTemplate:
    """The gate and the template must agree. This is the regression."""

    def test_ticked_template_passes(self) -> None:
        body = _TEMPLATE.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
        assert _run_gate(body) == 0

    def test_untouched_template_fails(self) -> None:
        """An unticked box is not acceptance, however the template is worded."""
        assert _run_gate(_TEMPLATE.read_text(encoding="utf-8")) == 1

    def test_template_still_contains_the_version_token(self) -> None:
        """A positive control: the assertion above would be vacuous without it."""
        assert f"Reveille-CLA-{_cla_version()}" in _TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.unit
class TestClaGateRejectsNonAcceptance:
    """The tightening the wrapped-line pattern was reaching for, kept."""

    def test_unrelated_ticked_box_plus_stray_version_fails(self) -> None:
        body = "- [x] I ran the tests\n\nSee Reveille-CLA-1.0 for details.\n"
        assert _run_gate(body) == 1

    def test_version_in_a_following_paragraph_does_not_count(self) -> None:
        body = "- [x] I accept the agreement\nReveille-CLA-1.0\n"
        assert _run_gate(body) == 1

    def test_wrong_version_fails(self) -> None:
        body = (
            "- [x] I accept the Reveille Contributor Licence Agreement\n  (`Reveille-CLA-0.9`).\n"
        )
        assert _run_gate(body) == 1

    def test_empty_body_fails(self) -> None:
        assert _run_gate("") == 1

    def test_commented_out_acceptance_does_not_count(self) -> None:
        body = "<!--\n- [x] I accept `Reveille-CLA-1.0`\n-->\n"
        assert _run_gate(body) == 1

    def test_single_line_acceptance_still_passes(self) -> None:
        """The form the previous pattern allowed must keep working."""
        assert _run_gate("- [x] I accept `Reveille-CLA-1.0`.\n") == 0
