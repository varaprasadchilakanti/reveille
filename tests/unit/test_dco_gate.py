# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The DCO half of the contributor-agreement workflow, executed.

The gate is a shell-embedded Python script inside
`.github/workflows/cla.yml`. It is extracted and run here against
throwaway repositories, so what is tested is the script that ships
rather than a copy of it. The CLA half is covered by
`tests/unit/test_cla_gate.py`.

The remediation path exists for a real case. A commit made through the
GitHub web interface -- applying a review suggestion, accepting a CodeQL
autofix, editing a file in the browser -- has no way to carry a
`Signed-off-by` trailer, and rewriting already-pushed history to insert
one is worse than recording the certification separately. Two such
commits landed on the 0.8.0 release branch and the gate had no answer
for them but a force-push.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cla.yml"

_SIGN_OFF = "\n\nSigned-off-by: Test Person <test@example.com>"
_REMEDIATION = (
    "I, Test Person <test@example.com>, hereby add my Signed-off-by to this commit: {sha}"
)


def _gate_script() -> str:
    """Return the DCO script as the workflow ships it."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    step = workflow[workflow.index("- name: Every commit is signed off") :]
    match = re.search(r"          python3 - <<'PY'\n(.*?)\n          PY", step, re.DOTALL)
    assert match is not None, "the DCO step no longer embeds a python heredoc"
    return textwrap.dedent(match.group(1))


class _Repository:
    """A throwaway repository the gate can be run against, repeatedly.

    Commits are added one at a time and the gate re-run in place, so a
    remediation can name a SHA that exists in the repository it is
    checked against.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.name", "Test Person")
        self._git("config", "user.email", "test@example.com")
        (path / "seed").write_text("0", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"seed{_SIGN_OFF}")
        self.base = self._git("rev-parse", "HEAD")
        self._files = 0

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    @property
    def head(self) -> str:
        """The current tip."""
        return self._git("rev-parse", "HEAD")

    def commit(self, message: str) -> str:
        """Add one commit and return its full SHA.

        `{sha}` in the message is replaced with the current tip, so a
        remediation can name the commit before it.
        """
        (self.path / f"file{self._files}").write_text(str(self._files), encoding="utf-8")
        self._files += 1
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message.format(sha=self.head))
        return self.head

    def check(self) -> tuple[int, str]:
        """Run the shipped gate over base..HEAD."""
        completed = subprocess.run(
            [sys.executable, "-c", _gate_script()],
            cwd=self.path,
            capture_output=True,
            text=True,
            env={**os.environ, "BASE": self.base, "HEAD": self.head},
            timeout=60,
        )
        return completed.returncode, completed.stdout + completed.stderr


def _run(tmp_path: Path, messages: list[str]) -> tuple[int, str]:
    """Build a repository with these commit messages and run the gate."""
    repository = _Repository(tmp_path)
    for message in messages:
        repository.commit(message)
    return repository.check()


@pytest.mark.unit
class TestTheOrdinaryCases:
    def test_every_commit_signed_off_passes(self, tmp_path: Path) -> None:
        code, output = _run(tmp_path, [f"one{_SIGN_OFF}", f"two{_SIGN_OFF}"])
        assert code == 0, output
        assert "commits are signed off" in output

    def test_one_unsigned_commit_fails(self, tmp_path: Path) -> None:
        code, output = _run(tmp_path, [f"one{_SIGN_OFF}", "two"])
        assert code == 1
        assert "missing Signed-off-by trailer" in output

    def test_the_error_names_the_offending_commit(self, tmp_path: Path) -> None:
        _, output = _run(tmp_path, [f"one{_SIGN_OFF}", "two"])
        assert "two" in output


@pytest.mark.unit
class TestRemediation:
    """Certification a person makes in writing, for a commit that cannot."""

    def test_a_remediation_commit_covers_an_earlier_one(self, tmp_path: Path) -> None:
        code, output = _run(tmp_path, ["web ui commit", _REMEDIATION + _SIGN_OFF])
        assert code == 0, output

    @pytest.mark.parametrize(
        "wrapped",
        [
            "I, Test Person <test@example.com>, hereby add my\nSigned-off-by to this commit: {sha}",
            "I, Test Person <test@example.com>, hereby add my Signed-off-by\nto this commit: {sha}",
            "I, Test Person\n<test@example.com>, hereby add my Signed-off-by to this commit: {sha}",
        ],
    )
    def test_a_wrapped_declaration_still_counts(self, tmp_path: Path, wrapped: str) -> None:
        """Commit messages wrap, and so does the template printed on failure.

        Requiring the declaration on one physical line is the defect this
        release already fixed once in the checkbox check above: the
        wording a contributor was told to copy did not fit on a line, so
        the gate could never match what it asked for. It was reintroduced
        here, and caught by running the gate over this repository's own
        branch rather than by any test.
        """
        code, output = _run(tmp_path, ["web ui commit", wrapped + _SIGN_OFF])
        assert code == 0, output

    def test_the_printed_template_satisfies_the_pattern_it_teaches(self, tmp_path: Path) -> None:
        """Follow the instructions literally; the gate must then pass.

        This closes the class of defect rather than an instance of it:
        whatever the failure message tells a contributor to write,
        writing exactly that has to work.

        It runs in **one** repository. An earlier version lifted the
        template from a failure in one throwaway repository and applied
        it in a second, where the SHA it named did not exist. That passed
        locally and on three Python versions and failed on the fourth,
        because two identical commits made in the same second hash
        identically and in different seconds do not. A test that passes
        for the wrong reason is worse than one that fails.
        """
        repository = _Repository(tmp_path)
        repository.commit("web ui commit")

        code, output = repository.check()
        assert code == 1, "the unsigned commit should have failed the gate"

        # The template is the indented block of the failure message, and
        # it names this repository's own commit.
        template = "\n".join(
            line[4:] for line in output.splitlines() if line.startswith("    ")
        ).strip()
        assert "hereby add my" in template, f"no template in the output:\n{output}"
        assert repository.head in template, "the template names some other commit"

        repository.commit(
            template.replace("Your Name", "Test Person").replace(
                "you@example.com", "test@example.com"
            )
        )
        code, after = repository.check()
        assert code == 0, (
            "copying the template the gate prints does not satisfy the gate:\n"
            f"{template}\n---\n{after}"
        )

    def test_an_unsigned_remediation_does_not_rescue_anything(self, tmp_path: Path) -> None:
        """Both commits fail, and the second cannot cover the first.

        The script also refuses to read a remediation out of an unsigned
        commit. That condition is belt and braces rather than
        independently observable: an unsigned remediation fails its own
        check, so the range never passes either way. Verified by
        mutation -- removing the condition changes no outcome.
        """
        code, output = _run(tmp_path, ["web ui commit", _REMEDIATION])
        assert code == 1
        assert output.count("missing Signed-off-by trailer") == 2

    def test_a_remediation_naming_another_commit_does_not_cover_this_one(
        self, tmp_path: Path
    ) -> None:
        wrong = _REMEDIATION.format(sha="0" * 40)
        code, _ = _run(tmp_path, ["web ui commit", wrong + _SIGN_OFF, f"later{_SIGN_OFF}"])
        assert code == 1

    def test_an_abbreviated_sha_does_not_cover_a_commit(self, tmp_path: Path) -> None:
        """A short SHA is rejected, and so is a genuine prefix of the target.

        The pattern requires all forty characters. That is strictness
        rather than a load-bearing check -- the lookup is an exact match
        against the full SHA, so a prefix would fail to match anyway.
        """
        for index, named in enumerate(("abc1234", "0" * 7)):
            short = (
                "I, Test Person <test@example.com>, hereby add my "
                f"Signed-off-by to this commit: {named}"
            )
            # A fresh repository per case: `_run` seeds one, so reusing a
            # directory leaves the second call with nothing to commit.
            workspace = tmp_path / f"case{index}"
            workspace.mkdir()
            code, _ = _run(workspace, ["web ui commit", short + _SIGN_OFF])
            assert code == 1, f"a remediation naming {named!r} was accepted"


@pytest.mark.unit
class TestTheFailureMessageIsActionable:
    """A gate that fails without saying what to do is a wall."""

    def test_it_names_both_routes_and_the_repository_setting(self, tmp_path: Path) -> None:
        _, output = _run(tmp_path, ["unsigned"])
        assert "git rebase --signoff" in output, "no route for your own commits"
        assert "web-based commits" in output, (
            "the setting that stops this recurring is not mentioned"
        )
        # The whole template, not just its first line: a reader who cannot
        # copy it verbatim has to guess at the wording, and the gate then
        # rejects the guess.
        for fragment in (
            "I, Your Name <you@example.com>, hereby add my",
            "Signed-off-by to this commit:",
            "Signed-off-by: Your Name <you@example.com>",
        ):
            assert fragment in output, f"the remediation template omits {fragment!r}"
