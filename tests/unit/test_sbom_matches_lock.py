# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`.github/scripts/sbom_matches_lock.py` passes only an SBOM that lists the lock's runtime graph.

The last two tests check that the release and `make sbom` run it: a check nothing runs guards
nothing, and they keep the script and its callers in one place.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / ".github" / "scripts" / "sbom_matches_lock.py"

_LOCK = """\
[[package]]
name = "typer"
version = "0.28.0"
groups = ["main"]

[[package]]
name = "pydantic_core"
version = "2.50.2"
groups = ["main"]

[[package]]
name = "colorama"
version = "0.4.6"
groups = ["main", "dev"]
markers = {main = "platform_system == \\"Windows\\"", dev = "sys_platform == \\"win32\\""}

[[package]]
name = "pytest"
version = "9.0.0"
groups = ["dev"]
"""

_RUNTIME = [("typer", "0.28.0"), ("pydantic-core", "2.50.2"), ("colorama", "0.4.6")]


def _check(
    tmp_path: Path, components: list[tuple[str, str]] | None
) -> subprocess.CompletedProcess[str]:
    lock = tmp_path / "poetry.lock"
    lock.write_text(_LOCK, encoding="utf-8")
    sbom = tmp_path / "sbom.json"
    body = (
        {}
        if components is None
        else {"components": [{"name": n, "version": v} for n, v in components]}
    )
    sbom.write_text(json.dumps(body), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(_SCRIPT), str(sbom), str(lock)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )


def test_an_sbom_listing_the_runtime_group_passes(tmp_path: Path) -> None:
    result = _check(tmp_path, _RUNTIME)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 runtime packages" in result.stdout


def test_names_are_compared_as_pep_503_normalises_them(tmp_path: Path) -> None:
    """The lock writes `pydantic_core`; an SBOM may write `Pydantic-Core`."""
    result = _check(
        tmp_path, [("typer", "0.28.0"), ("Pydantic-Core", "2.50.2"), ("colorama", "0.4.6")]
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("body", [None, []], ids=["no-components-key", "empty-list"])
def test_an_sbom_with_no_components_fails(
    tmp_path: Path, body: list[tuple[str, str]] | None
) -> None:
    """cyclonedx-py exits 0 with an empty SBOM when it finds no dependencies table."""
    result = _check(tmp_path, body)

    assert result.returncode == 1
    assert "lists no components" in result.stdout


def test_a_package_installed_on_one_platform_only_is_required(tmp_path: Path) -> None:
    """An SBOM built from one machine's environment drops `colorama` off Windows."""
    result = _check(tmp_path, [("typer", "0.28.0"), ("pydantic-core", "2.50.2")])

    assert result.returncode == 1
    assert "missing from the SBOM: colorama 0.4.6" in result.stdout


def test_a_development_package_fails(tmp_path: Path) -> None:
    result = _check(tmp_path, [*_RUNTIME, ("pytest", "9.0.0")])

    assert result.returncode == 1
    assert "not in the lock's runtime group: pytest 9.0.0" in result.stdout


def test_a_different_version_fails(tmp_path: Path) -> None:
    result = _check(
        tmp_path, [("typer", "0.27.3"), ("pydantic-core", "2.50.2"), ("colorama", "0.4.6")]
    )

    assert result.returncode == 1
    assert "missing from the SBOM: typer 0.28.0" in result.stdout
    assert "not in the lock's runtime group: typer 0.27.3" in result.stdout


def test_a_nested_component_counts(tmp_path: Path) -> None:
    """CycloneDX allows components inside components; one there is still listed."""
    lock = tmp_path / "poetry.lock"
    lock.write_text(_LOCK, encoding="utf-8")
    sbom = tmp_path / "sbom.json"
    nested = {"name": "colorama", "version": "0.4.6"}
    top = [
        {"name": "typer", "version": "0.28.0", "components": [nested]},
        {"name": "pydantic-core", "version": "2.50.2"},
    ]
    sbom.write_text(json.dumps({"components": top}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), str(sbom), str(lock)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_an_sbom_that_is_not_an_object_exits_2(tmp_path: Path) -> None:
    sbom = tmp_path / "sbom.json"
    sbom.write_text("[]", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), str(sbom), str(_ROOT / "poetry.lock")],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )

    assert result.returncode == 2
    assert "not a JSON object" in result.stderr


def test_an_unreadable_input_exits_2(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(tmp_path / "absent.json"),
            str(tmp_path / "absent.lock"),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )

    assert result.returncode == 2
    assert "cannot read the inputs" in result.stderr


def test_the_release_checks_the_sbom_before_attesting_it() -> None:
    """The check sits between generating the SBOM and attesting it, on the same file."""
    workflow = (_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    steps = [
        "      - name: Generate CycloneDX SBOM\n",
        "      - name: Check the SBOM against the lock\n",
        "      - name: Attest the SBOM\n",
    ]
    positions = [workflow.find(step) for step in steps]

    assert -1 not in positions, positions
    assert positions == sorted(positions)
    check = workflow[positions[1] : positions[2]]
    assert 'run: python3 .github/scripts/sbom_matches_lock.py "$SBOM_FILE" poetry.lock\n' in check


def test_make_sbom_checks_what_it_wrote() -> None:
    recipe = (
        (_ROOT / "Makefile").read_text(encoding="utf-8").split("\nsbom:", 1)[1].split("\n\n", 1)[0]
    )

    assert 'sbom_matches_lock.py "dist/reveille-$$VER-sbom.cdx.json" poetry.lock' in recipe
