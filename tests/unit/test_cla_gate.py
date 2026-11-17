"""The CLA gate must accept the pull-request template this repository ships.

These tests do not reimplement the check. They extract the script from
`.github/workflows/cla.yml` and run it, so what is asserted is the code that
actually gates contributions.

The acceptance pattern must match the tick and the CLA version across the
physical lines the shipped template wraps that bullet over; otherwise every
pull request using the template fails the gate and is told to tick a box it
has already ticked.
"""

from __future__ import annotations

import hashlib
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


@pytest.mark.unit
class TestFalseAcceptances:
    """Bodies that do not show acceptance must not pass."""

    @pytest.mark.parametrize(
        "body",
        [
            "```\n- [x] I accept the Reveille Contributor Licence Agreement (`Reveille-CLA-1.0`).\n```\n",
            "<!--\n- [x] I accept the Reveille Contributor Licence Agreement (`Reveille-CLA-1.0`).\n",
            "- [x] I do NOT accept the Reveille Contributor Licence Agreement (`Reveille-CLA-1.0`).\n",
            "- [x] I accept the Reveille Contributor Licence Agreement (`Reveille-CLA-1.01`).\n",
            "- [x] I accept the Reveille Contributor Licence Agreement (`Reveille-CLA-1.0x`).\n",
        ],
    )
    def test_it_is_refused(self, body: str) -> None:
        assert _run_gate(body) == 1

    def test_the_plain_acceptance_still_passes(self) -> None:
        body = "- [x] I accept the Reveille Contributor Licence Agreement (`Reveille-CLA-1.0`).\n"
        assert _run_gate(body) == 0


# The text contributors accepted as 1.0. A changed agreement is a new version with a new
# copy beside this one (CLA.md §6.5, ADR 0009); this copy never changes.
_CLA_1_0_SHA256 = "1f1ec19111b7460f3d872fcc85e59a1e6d728f14854fac56f82733f887f64a9e"


@pytest.mark.unit
class TestTheAgreementTextIsVersioned:
    def test_cla_md_is_the_copy_kept_for_the_version_the_gate_requires(self) -> None:
        kept = _ROOT / "docs" / "cla" / f"CLA-{_cla_version()}.md"

        assert kept.is_file(), f"no copy of the agreement at {kept}"
        assert (_ROOT / "CLA.md").read_bytes() == kept.read_bytes(), (
            "CLA.md differs from the text accepted under this version: "
            "a changed agreement needs a new version"
        )

    def test_the_1_0_text_is_unchanged(self) -> None:
        text = (_ROOT / "docs" / "cla" / "CLA-1.0.md").read_bytes()

        assert hashlib.sha256(text).hexdigest() == _CLA_1_0_SHA256


def _tree_script() -> str:
    """The workflow's check that the body's checks ran on the head's tree."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"python3 - <<'TREE'\n(.*?)\n[ \t]*TREE\n", text, re.DOTALL)
    assert match is not None, "could not find the tree script in cla.yml"
    lines = match.group(1).split("\n")
    indent = min(len(ln) - len(ln.lstrip()) for ln in lines if ln.strip())
    return "\n".join(ln[indent:] for ln in lines)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=A", "-c", "user.email=a@e.test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def checked(tmp_path: Path) -> tuple[Path, str]:
    """A repository and the commit its checks ran on."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a").write_text("1\n", encoding="utf-8")
    _git(tmp_path, "add", "a")
    _git(tmp_path, "commit", "-qm", "a")
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def _run_tree(repo: Path, body: str) -> int:
    head = _git(repo, "rev-parse", "HEAD")
    return subprocess.run(
        [sys.executable, "-c", _tree_script()],
        cwd=repo,
        env={"PR_BODY": body, "HEAD": head, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    ).returncode


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="the workflow runs on Linux")
class TestTheBodyIsTiedToTheCheckedTree:
    def test_no_line_is_not_compared(self, checked: tuple[Path, str]) -> None:
        assert _run_tree(checked[0], "## Verified\n") == 0

    def test_the_head_itself(self, checked: tuple[Path, str]) -> None:
        assert _run_tree(checked[0], f"Checked at `{checked[1]}`.") == 0

    def test_an_empty_commit_after_it(self, checked: tuple[Path, str]) -> None:
        _git(checked[0], "commit", "-q", "--allow-empty", "-m", "sign off")
        assert _run_tree(checked[0], f"Checked at `{checked[1]}`.") == 0

    def test_a_change_after_it_fails(self, checked: tuple[Path, str]) -> None:
        (checked[0] / "a").write_text("2\n", encoding="utf-8")
        _git(checked[0], "commit", "-qam", "late")
        assert _run_tree(checked[0], f"Checked at `{checked[1]}`.") == 1

    def test_a_commit_not_in_the_branch_fails(self, checked: tuple[Path, str]) -> None:
        """Same tree, other history: a rewrite since the checks ran."""
        _git(checked[0], "commit", "-q", "--amend", "--allow-empty", "-m", "rewritten")
        assert _run_tree(checked[0], f"Checked at `{checked[1]}`.") == 1

    def test_a_line_in_a_comment_is_not_compared(self, checked: tuple[Path, str]) -> None:
        body = f"<!-- Checked at `{'0' * 40}`. -->"
        assert _run_tree(checked[0], body) == 0

    def test_a_commit_not_in_the_clone_is_named_so(self, checked: tuple[Path, str]) -> None:
        done = subprocess.run(
            [sys.executable, "-c", _tree_script()],
            cwd=checked[0],
            env={
                "PR_BODY": f"Checked at `{'0' * 40}`.",
                "HEAD": checked[1],
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
        )
        assert done.returncode == 1 and "is not in this repository" in done.stdout
