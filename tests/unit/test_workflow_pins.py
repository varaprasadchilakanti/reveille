"""Supply-chain tests for the GitHub Actions workflow definitions.

A third-party action referenced by a mutable tag executes whatever that
tag points at on the day the workflow runs, which is an arbitrary-code
seam in the release path. Every action must therefore be pinned to an
immutable commit SHA.

A bare SHA is unreadable, so the convention is a trailing comment naming
the exact version it resolves to. That comment is the only thing telling
a reviewer whether a pin is current, so it must name a precise version:
`# v1` says nothing a reviewer can act on, and `# release/v1` -- the
comment this file was written to stop recurring -- says less.

These assertions cannot verify that a comment is *truthful*; nothing
local can, since that requires resolving the SHA against GitHub. They
enforce the shape. Truthfulness is checked when a pin is added or bumped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# `uses: owner/repo@ref` with an optional trailing `# comment`.
_USES = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>\S+)@(?P<ref>\S+?)\s*(?:#\s*(?P<comment>.*?))?$"
)

_SHA = re.compile(r"^[0-9a-f]{40}$")

# A precise version: at least `vMAJOR.MINOR`. Deliberately rejects a bare
# `v1`, which is a moving major-tag alias rather than a resolved version.
_PRECISE_VERSION = re.compile(r"^v\d+\.\d+(\.\d+)?$")


def _pins() -> list[tuple[str, int, str, str, str | None]]:
    """Collect every `uses:` reference across all workflow files.

    Returns:
        Tuples of (file name, line number, action, ref, comment).
    """
    found = []
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(line)
            if match is not None:
                found.append(
                    (
                        path.name,
                        lineno,
                        match.group("action"),
                        match.group("ref"),
                        match.group("comment"),
                    )
                )
    return found


@pytest.mark.unit
class TestWorkflowPins:
    """Tests for immutable, legible action pins."""

    def test_workflows_are_discovered(self) -> None:
        """Guard the guard.

        Every assertion below is vacuously true if the glob finds
        nothing -- a renamed directory would silently disable the whole
        file rather than fail it.
        """
        pins = _pins()
        assert len(pins) >= 10, f"expected the workflow set to be found, got {len(pins)} pins"

    def test_every_action_is_pinned_to_a_sha(self) -> None:
        offenders = [
            f"{name}:{lineno} {action}@{ref}"
            for name, lineno, action, ref, _ in _pins()
            if not _SHA.match(ref)
        ]
        assert not offenders, (
            "actions referenced by mutable ref instead of commit SHA:\n" + "\n".join(offenders)
        )

    def test_every_pin_names_a_precise_version(self) -> None:
        offenders = [
            f"{name}:{lineno} {action} -> {comment!r}"
            for name, lineno, action, _, comment in _pins()
            if comment is None or not _PRECISE_VERSION.match(comment.strip())
        ]
        assert not offenders, (
            "pins whose comment does not name a precise version (vMAJOR.MINOR[.PATCH]):\n"
            + "\n".join(offenders)
        )
