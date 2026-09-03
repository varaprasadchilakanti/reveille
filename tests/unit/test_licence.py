"""Unit tests for the licence declarations.

Reveille declares its licence in five places: `LICENSE`, the
`pyproject.toml` licence field, the Trove classifier, the runtime
constant `reveille.__licence__`, and an SPDX header in every source
file. Before v0.8.0 nothing checked that any of them agreed, so
`__licence__` could have drifted from `LICENSE` silently and for any
length of time -- the same class of defect `make check-version` exists
to prevent for the version string.

`make check-licence` covers the first three at build time. This module
covers what a shell target cannot check cheaply: that every source file
carries an SPDX header, and that it names the same licence as everything
else.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

import pytest

import reveille

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = Path(reveille.__file__).parent
_EXPECTED = "Apache-2.0"

# SHA-256 of the canonical Apache License 2.0 text (11,358 bytes).
_APACHE_2_0_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"

# The template is a Jinja file, so its header is a Jinja comment rather than a
# Python one. Both forms are matched, because "every source file" has to mean
# every file that ships -- the template is in the wheel, and a file that leaves
# the repository without a header carries no licence information at all.
_SPDX = re.compile(r"^(?:# |\{# )SPDX-License-Identifier: (?P<identifier>[^\s#]+)", re.MULTILINE)
_COPYRIGHT = re.compile(r"^(?:# |\{# )SPDX-FileCopyrightText: \d{4} .+$", re.MULTILINE)


def _source_files() -> list[Path]:
    """Every shipped source file that can carry a comment header."""
    return sorted(p for p in _SRC.rglob("*") if p.suffix in {".py", ".j2"})


def _pyproject() -> dict[str, object]:
    with (_REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


@pytest.mark.unit
class TestLicenceDeclarationsAgree:
    """Every place the licence is stated must state the same licence."""

    def test_runtime_constant_matches_pyproject(self) -> None:
        """`reveille.__licence__` matches the packaging metadata.

        The constant is what a downstream program reads at runtime; the
        metadata is what PyPI displays. They are written in different
        files and nothing but this test relates them.
        """
        poetry = _pyproject()["tool"]["poetry"]  # type: ignore[index]
        assert reveille.__licence__ == poetry["license"] == _EXPECTED  # type: ignore[index]

    def test_licence_file_is_the_apache_text(self) -> None:
        """`LICENSE` holds the Apache-2.0 text, not a description of it.

        The file is the canonical text verbatim. Editing it -- even to
        fill in the appendix placeholders -- risks breaking automated
        licence detection, which matches against the known text.
        """
        raw = (_REPO_ROOT / "LICENSE").read_bytes()
        text = raw.decode("utf-8")

        # Pinned by digest, not by substring. Substring checks pass on a file
        # that contains the MIT text *plus* the two strings being grepped for,
        # which is not a licence check -- it is a spell check. The canonical
        # Apache-2.0 text is 11,358 bytes with this digest; any edit at all,
        # including filling in the appendix placeholders, breaks automated
        # licence detection, so any edit at all should break this test.
        assert hashlib.sha256(raw).hexdigest() == _APACHE_2_0_SHA256, (
            "LICENSE is not the canonical Apache-2.0 text byte for byte. "
            "If this was deliberate, the licence has changed and every other "
            "declaration must change with it."
        )

        # Kept as diagnostics: these say *what* is wrong when the digest fails.
        assert "Apache License" in text
        assert "Version 2.0, January 2004" in text
        assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text
        assert "Permission is hereby granted, free of charge" not in text, (
            "LICENSE contains MIT permission text"
        )

    def test_classifier_matches_the_declared_licence(self) -> None:
        """The Trove classifier agrees with the licence field.

        PEP 639 deprecates licence classifiers in favour of an SPDX
        `License-Expression`, but Poetry 1.8 emits neither, so the
        classifier remains the only structured licence metadata in the
        distribution. While it is there, it must not contradict.
        """
        classifiers = _pyproject()["tool"]["poetry"]["classifiers"]  # type: ignore[index]
        licence_classifiers = [c for c in classifiers if c.startswith("License ::")]  # type: ignore[union-attr]

        assert licence_classifiers == ["License :: OSI Approved :: Apache Software License"]


@pytest.mark.unit
class TestSpdxHeaders:
    """Apache-2.0 recommends tagging each file in case it is detached."""

    def test_every_source_file_declares_the_licence(self) -> None:
        """No source file may be missing its SPDX identifier.

        A file that leaves the repository without one carries no licence
        information at all, which is the situation the header exists to
        prevent.
        """
        missing = sorted(
            str(path.relative_to(_SRC))
            for path in _source_files()
            if not _SPDX.search(path.read_text(encoding="utf-8"))
        )
        assert not missing, f"source files without an SPDX-License-Identifier: {missing}"

    def test_every_source_file_declares_a_copyright_holder(self) -> None:
        """The identifier says which licence; this says whose work it is."""
        missing = sorted(
            str(path.relative_to(_SRC))
            for path in _source_files()
            if not _COPYRIGHT.search(path.read_text(encoding="utf-8"))
        )
        assert not missing, f"source files without an SPDX-FileCopyrightText: {missing}"

    def test_no_source_file_declares_a_different_licence(self) -> None:
        """A stale header is worse than none: it is a false statement."""
        wrong = sorted(
            (str(path.relative_to(_SRC)), match.group("identifier"))
            for path in _source_files()
            if (match := _SPDX.search(path.read_text(encoding="utf-8")))
            and match.group("identifier") != _EXPECTED
        )
        assert not wrong, f"source files declaring a licence other than {_EXPECTED}: {wrong}"
