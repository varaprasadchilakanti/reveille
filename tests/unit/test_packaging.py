"""Unit tests for Reveille's packaging contract.

These verify claims the distribution metadata makes about the package.
A claim that nothing checks is a claim that silently stops being true:
the `Typing :: Typed` classifier was advertised for several releases
while no marker file shipped, so every downstream type checker ignored
Reveille's annotations.

The build-time counterpart is `make check-packaging`, which asserts the
marker survives into the built wheel and sdist. This module asserts it
exists in the package at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import reveille

_PACKAGE_ROOT = Path(reveille.__file__).parent


@pytest.mark.unit
class TestPep561Marker:
    """Tests for the PEP 561 inline-type marker."""

    def test_py_typed_marker_is_present(self) -> None:
        """PEP 561 requires the marker for annotations to be honoured.

        Without it a downstream `mypy` run reports Reveille as missing
        library stubs, regardless of how completely the source is typed.
        """
        assert (_PACKAGE_ROOT / "py.typed").is_file()

    def test_py_typed_marker_is_empty(self) -> None:
        """An empty marker declares the package fully typed inline.

        PEP 561 reserves the contents for the string `partial`, which
        marks a stub-only package that covers part of its API. Reveille
        ships complete inline annotations, so the file stays empty.
        """
        assert (_PACKAGE_ROOT / "py.typed").read_text(encoding="utf-8").strip() == ""
