"""Unit tests for `poetry.lock` integrity.

`poetry.lock` is generated TOML. Nothing in the repository used to
assert it was even parseable, and on 2026-09-02 that gap cost six
consecutive red builds on `main`: a merge conflict inside plotly's
`[package.extras]` table was resolved by deleting the conflict markers
and keeping both sides, which duplicated four keys. Duplicate keys are a
TOML syntax error, so every job that ran `poetry install` failed with
"Unable to read the lock file" -- an error that names the symptom and
not the cause.

Three guards now cover this, deliberately at different layers:

* `.gitattributes` marks the file `-merge`, so Git will not write
  conflict markers into it and it cannot be hand-merged at all.
* `make check-lock` runs in CI *before* anything installs, using only
  the standard library -- a gate that needed Poetry could never report,
  because a broken lock is precisely what stops Poetry running.
* This module, which keeps the invariant visible in the test suite
  rather than only in build tooling.

The redundancy is intentional. The `.gitattributes` rule prevents the
known cause; these tests catch any future cause.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCKFILE = _REPO_ROOT / "poetry.lock"


@pytest.mark.unit
class TestLockfileIntegrity:
    """Tests that `poetry.lock` is a file Poetry can actually read."""

    def test_lockfile_exists(self) -> None:
        """A committed lock file is what makes installs reproducible.

        `.gitignore` documents the decision to track it; this asserts the
        decision still holds.
        """
        assert _LOCKFILE.is_file(), f"poetry.lock is missing from {_REPO_ROOT}"

    def test_lockfile_is_valid_toml(self) -> None:
        """The lock parses under a strict TOML reader.

        `tomllib` rejects duplicate keys, which is the specific defect
        that a hand-resolved merge conflict introduces. Poetry's own
        reader rejects it too, but only once an install is already under
        way; this fails earlier and says why.
        """
        try:
            tomllib.loads(_LOCKFILE.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:  # pragma: no cover - failure path
            pytest.fail(
                f"poetry.lock is not valid TOML: {exc}\n"
                "A generated lock file must never be hand-merged. "
                "Regenerate it with: poetry lock --no-update"
            )

    def test_lockfile_declares_metadata(self) -> None:
        """The lock carries the metadata Poetry and the SBOM rely on.

        `make sbom` and the release SBOM job read this file as their sole
        source of truth for the runtime dependency graph, so a lock that
        parses but carries no package metadata would produce a confident,
        empty bill of materials.
        """
        data = tomllib.loads(_LOCKFILE.read_text(encoding="utf-8"))

        assert "metadata" in data, "poetry.lock has no [metadata] table"
        assert "lock-version" in data["metadata"], "poetry.lock declares no lock-version"
        assert data.get("package"), "poetry.lock lists no packages"

    def test_no_conflict_markers(self) -> None:
        """No merge-conflict markers survive in the lock.

        This guards an *adjacent* mistake, not the one that caused the
        2026-09-02 incident. There the markers were deleted and both sides
        kept, so the file contained no markers at all and this check would
        have passed -- only `test_lockfile_is_valid_toml` catches that.

        It is still worth having: committing a lock with the markers left in
        is the other half of the same error, and it is cheap to detect.
        """
        text = _LOCKFILE.read_text(encoding="utf-8")
        offenders = [
            f"line {n}: {line}"
            for n, line in enumerate(text.splitlines(), start=1)
            if line.startswith(("<<<<<<<", "=======", ">>>>>>>"))
        ]
        assert not offenders, "merge conflict markers in poetry.lock:\n" + "\n".join(offenders)
