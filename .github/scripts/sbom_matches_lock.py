# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Check that a CycloneDX SBOM lists exactly the runtime packages in `poetry.lock`.

Usage: sbom_matches_lock.py SBOM.json poetry.lock

The runtime packages are the lock's `main` group on every platform, including those
that install only under a marker, such as `colorama` on Windows. Names are compared as
PEP 503 normalises them, together with their versions. Exit 0 on a match, 1 on an
empty SBOM or a difference, 2 when either file cannot be read.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib


def _normalise(name: str) -> str:
    """Return the PEP 503 normalised form of a distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_runtime(lock: dict[str, object]) -> set[tuple[str, str]]:
    """Return (name, version) for each package the lock's `main` group installs."""
    packages = lock.get("package", [])
    if not isinstance(packages, list):
        raise TypeError("the lock has no list of packages")
    return {
        (_normalise(package["name"]), package["version"])
        for package in packages
        if "main" in package.get("groups", [])
    }


def sbom_components(sbom: object) -> set[tuple[str, str]]:
    """Return (name, version) for each component the SBOM lists, nested ones included."""
    if not isinstance(sbom, dict):
        raise TypeError("the SBOM is not a JSON object")
    components = sbom.get("components", [])
    if not isinstance(components, list):
        raise TypeError("the SBOM's components are not a list")
    found = set()
    for component in components:
        found.add((_normalise(component["name"]), component.get("version", "")))
        found |= sbom_components(component)
    return found


def compare(sbom: set[tuple[str, str]], lock: set[tuple[str, str]]) -> list[str]:
    """Return one line per problem; an empty list means the SBOM matches the lock."""
    if not sbom:
        return ["the SBOM lists no components"]
    return [f"missing from the SBOM: {name} {version}" for name, version in sorted(lock - sbom)] + [
        f"not in the lock's runtime group: {name} {version}"
        for name, version in sorted(sbom - lock)
    ]


def main(argv: list[str]) -> int:
    """Compare the SBOM with the lock and report each difference."""
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as handle:
            sbom = json.load(handle)
        with open(argv[1], "rb") as handle:
            lock = tomllib.load(handle)
        runtime = lock_runtime(lock)
        problems = compare(sbom_components(sbom), runtime)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"sbom_matches_lock: cannot read the inputs: {error!r}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"SBOM matches the lock: {len(runtime)} runtime packages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
