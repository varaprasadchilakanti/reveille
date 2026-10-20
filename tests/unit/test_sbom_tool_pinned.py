# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The SBOM generator is installed by version and hash, in CI and by `make sbom`.

The release job installed `cyclonedx-bom==7.3.1` with its dependencies
unpinned, in a job that can mint a Sigstore identity. The SBOM also names the
version of `cyclonedx-python-lib` that wrote it, so the same `poetry.lock` gave
a different SBOM once that library moved from 11.11.0 to 11.12.0, and the
promise in SECURITY.md that `make sbom` reproduces a published one held only
by luck.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_REQUIREMENTS = _ROOT / ".github" / "requirements" / "sbom.txt"
_INPUT = _ROOT / ".github" / "requirements" / "sbom.in"


def _pins() -> dict[str, list[str]]:
    """Map each pinned requirement to its hashes."""
    pins: dict[str, list[str]] = {}
    current = ""
    for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash=sha256:"):
            pins[current].append(stripped)
        else:
            current = stripped.removesuffix("\\").strip()
            pins[current] = []
    return pins


def test_every_requirement_is_one_version_with_a_hash() -> None:
    pins = _pins()

    assert "cyclonedx-bom==7.3.1" in pins, "positive control: the generator is pinned"
    for requirement, hashes in pins.items():
        assert re.fullmatch(r"[A-Za-z0-9._-]+==[A-Za-z0-9.]+", requirement), requirement
        assert hashes, f"{requirement} has no hash"


def test_the_input_names_the_pinned_generator() -> None:
    """`sbom.txt` is compiled from `sbom.in`; an edit to one alone is drift."""
    wanted = [
        line
        for line in _INPUT.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert wanted == ["cyclonedx-bom==7.3.1"]
    assert set(wanted) <= set(_pins())


@pytest.mark.parametrize(
    ("path", "install"),
    [
        (".github/workflows/publish.yml", "--require-hashes -r .github/requirements/sbom.txt"),
        ("Makefile", "--require-hashes -r $(SBOM_REQUIREMENTS)"),
    ],
)
def test_both_installs_require_the_hashes(path: str, install: str) -> None:
    text = (_ROOT / path).read_text(encoding="utf-8")

    assert install in text
    assert "cyclonedx-bom==" not in text, "a second, unhashed pin of the generator"


def test_the_makefile_rebuilds_a_venv_from_older_requirements() -> None:
    """A reused venv would keep the library version that changed the SBOM."""
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "SBOM_REQUIREMENTS := .github/requirements/sbom.txt" in makefile
    assert "$(SBOM_VENV)/installed: $(SBOM_REQUIREMENTS)" in makefile
    assert "sbom: $(SBOM_VENV)/installed" in makefile
