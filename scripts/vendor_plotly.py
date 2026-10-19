# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Vendor the plotly.js cartesian bundle, with the licence of every package it carries.

Run by the maintainer to change the chart library's version, never by Reveille:

    python scripts/vendor_plotly.py 4.1.1

It downloads from the npm registry and GitHub, checks every tarball against its
published integrity hash, and writes three files under `src/reveille/vendor/`:
the bundle exactly as published, a pin record, and the third-party notices each
report carries. Which packages the bundle carries is traced from the plotly.js
source: every `require` reachable from `lib/index-cartesian.js`, then each of those
packages' own dependencies, resolved from plotly.js's lockfile at the same tag.
A package reached only for a stylesheet (maplibre-gl) contributes that file
alone, so its dependencies are not followed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

_REGISTRY = "https://registry.npmjs.org"
_LOCKFILE = "https://raw.githubusercontent.com/plotly/plotly.js/v{version}/package-lock.json"
_VENDOR = Path(__file__).resolve().parent.parent / "src" / "reveille" / "vendor"
_DIST = "plotly.js-cartesian-dist-min"
_BUNDLE = "plotly-cartesian.min.js"
_LICENCE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")
# plotly.js's esbuild-config.js aliases these; the rest resolve as Node would.
_ALIASES = {"regl": "@plotly/regl", "stream": "stream-browserify"}
# Directories a package publishes that no bundle reaches.
_NOT_SHIPPED = ("test/", "tests/", "example/", "examples/", "bin/", "benchmark/")
_REQUIRE = re.compile(
    r"""require\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|^\s*import\s[^'"]*?from\s*['"]([^'"]+)['"]"""
    r"""|^\s*import\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
# The MIT text, for a package that declares MIT but publishes no licence file.
_MIT = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        data: bytes = response.read()
    return data


def _verified(url: str, integrity: str) -> bytes:
    """Download a tarball and check it against its `sha512-...` integrity value."""
    data = _fetch(url)
    algorithm, _, expected = integrity.partition("-")
    if algorithm != "sha512":
        # The registry's value chooses the algorithm; a weaker one is not accepted.
        sys.exit(f"{url}: integrity {integrity[:16]}... is not sha512")
    actual = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if actual != expected:
        sys.exit(f"{url}: integrity mismatch")
    return data


def _members(data: bytes) -> dict[str, bytes]:
    """Return the regular files of an npm tarball, by path below `package/`."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            _, _, rest = member.name.partition("/")
            if member.isfile() and rest and ".." not in rest.split("/"):
                handle = archive.extractfile(member)
                if handle is not None:
                    files[rest] = handle.read()
    return files


def _metadata(name: str, version: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_fetch(f"{_REGISTRY}/{name}/{version}"))
    return data


def _required_packages(source: Path) -> dict[str, set[str]]:
    """Return each npm package the bundle's source requires, with what it asks for."""
    seen: set[Path] = set()
    stack = [source / "lib" / "index-cartesian.js"]
    wanted: dict[str, set[str]] = {}
    while stack:
        path = stack.pop()
        if path in seen or path.suffix != ".js":
            continue
        seen.add(path)
        for match in _REQUIRE.finditer(path.read_text(encoding="utf-8")):
            spec = next(group for group in match.groups() if group)
            if spec.startswith("."):
                base = Path(os.path.normpath(path.parent / spec))
                if not base.is_relative_to(source):
                    sys.exit(f"{path}: requires {spec!r}, outside the plotly.js source")
                for candidate in (base, Path(f"{base}.js"), base / "index.js"):
                    if candidate.is_file():
                        stack.append(candidate)
                        break
            else:
                wanted.setdefault(_bare_name(spec), set()).add(spec)
    return wanted


def _bare_name(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _locate(name: str, parent: str, lock: dict[str, Any]) -> str | None:
    """Return the lockfile key Node would resolve `name` to from `parent`."""
    here = parent
    while True:
        key = f"{here}/node_modules/{name}" if here else f"node_modules/{name}"
        if key in lock:
            return key
        if not here:
            return None
        here = here.rsplit("/node_modules/", 1)[0] if "/node_modules/" in here else ""


def _bare_requires(files: dict[str, bytes]) -> set[str]:
    """Return the packages a package's own code requires by bare name."""
    names: set[str] = set()
    for path, content in files.items():
        if path.endswith(".js") and not path.startswith(_NOT_SHIPPED):
            for match in _REQUIRE.finditer(content.decode("utf-8", "replace")):
                spec = next(group for group in match.groups() if group)
                if not spec.startswith((".", "/")):
                    names.add(_bare_name(spec))
    return names


def _closure(
    wanted: dict[str, set[str]], lock: dict[str, Any]
) -> dict[str, tuple[dict[str, Any], dict[str, bytes]]]:
    """Resolve the packages, and what each one's code requires, through the lockfile.

    A package's declared dependencies are followed, and so is every bare
    `require` in its code that the lockfile can resolve: esbuild bundles the npm
    package for a Node built-in (`buffer`, `assert`, `events`) when one is
    installed, and plotly.js's build aliases `stream` to `stream-browserify`.
    Each package is downloaded once, checked against its integrity, and kept.
    """
    found: dict[str, tuple[dict[str, Any], dict[str, bytes]]] = {}
    stack = [(name, "", specs) for name, specs in wanted.items()]
    while stack:
        name, parent, specs = stack.pop()
        key = _locate(_ALIASES.get(name, name), parent, lock)
        if key is None:
            if not parent:
                sys.exit(f"{name} is not in the lockfile")
            continue  # a built-in with no npm package: esbuild cannot bundle it
        if key in found:
            continue
        files = _members(_verified(lock[key]["resolved"], lock[key]["integrity"]))
        found[key] = (lock[key], files)
        if specs and all(spec.endswith(".css") for spec in specs):
            continue  # a stylesheet alone is bundled, not the package's code
        required = set(lock[key].get("dependencies", {})) | _bare_requires(files)
        stack.extend((dep, key, set()) for dep in sorted(required))
    return found


def _licence_text(name: str, files: dict[str, bytes], declared: str, author: Any) -> str:
    """Return a package's licence files, or say plainly that it publishes none."""
    texts = [
        files[path].decode("utf-8", "replace").strip()
        for path in sorted(files)
        if "/" not in path and path.upper().startswith(_LICENCE_NAMES)
    ]
    if texts:
        return "\n\n".join(texts)
    readme = next(
        (files[p].decode("utf-8", "replace") for p in files if p.lower() == "readme.md"), ""
    )
    section = re.search(r"^#+\s*Licen[cs]e\s*$(.*?)(?=^#|\Z)", readme, re.M | re.S | re.I)
    if section and "Permission is hereby granted" in section.group(1):
        return section.group(1).strip().replace("&lt;", "<").replace("&gt;", ">")
    if isinstance(author, dict):
        author = author.get("name", "")
    if declared != "MIT":
        sys.exit(f"{name}: no licence file, and {declared} has no text here")
    return (
        f"No licence file is published with {name}. Its package.json declares the MIT\n"
        f"licence and names {author or 'no author'} as its author. The MIT licence:\n\n{_MIT}"
    ).strip()


def main(version: str) -> None:
    """Vendor the cartesian bundle at `version` and write its notices."""
    dist = _metadata(_DIST, version)
    bundle_files = _members(_verified(dist["dist"]["tarball"], dist["dist"]["integrity"]))
    bundle = bundle_files[_BUNDLE]

    plotly = _metadata("plotly.js", version)
    lock = json.loads(_fetch(_LOCKFILE.format(version=version)))["packages"]
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        for path, content in _members(
            _verified(plotly["dist"]["tarball"], plotly["dist"]["integrity"])
        ).items():
            if path.startswith(("src/", "lib/")):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(content)
        packages = _closure(_required_packages(root), lock)

    sections = [
        (
            f"plotly.js {version} (cartesian bundle, {_DIST}), MIT\n"
            "https://github.com/plotly/plotly.js",
            bundle_files["LICENSE"].decode().strip(),
        )
    ]
    record = []
    for key in sorted(packages, key=lambda k: k.rsplit("node_modules/", 1)[-1]):
        entry, files = packages[key]
        name = key.rsplit("node_modules/", 1)[-1]
        package_json = json.loads(files["package.json"])
        declared = entry.get("license") or package_json.get("license", "")
        sections.append(
            (
                f"{name} {entry['version']}, {declared}",
                _licence_text(name, files, declared, package_json.get("author")),
            )
        )
        record.append(
            {
                "name": name,
                "version": entry["version"],
                "license": declared,
                "integrity": entry["integrity"],
            }
        )

    rule = "=" * 72
    notices = (
        "Third-party software in every Reveille HTML report\n\n"
        f"The report embeds the plotly.js {version} cartesian bundle. The packages below are\n"
        "the ones its source requires, and their dependencies, traced from plotly.js at the\n"
        "same version. Each one's licence follows, as that package publishes it, with line\n"
        "endings and trailing spaces normalised.\n"
        + "".join(f"\n{rule}\n{title}\n{rule}\n\n{text}\n" for title, text in sections)
    )
    notices = "\n".join(line.rstrip() for line in notices.replace("\r\n", "\n").split("\n"))
    _VENDOR.mkdir(parents=True, exist_ok=True)
    (_VENDOR / _BUNDLE).write_bytes(bundle)
    (_VENDOR / "THIRD-PARTY-NOTICES.txt").write_text(notices, encoding="utf-8")
    pin = {
        "package": _DIST,
        "version": version,
        "tarball": dist["dist"]["tarball"],
        "integrity": dist["dist"]["integrity"],
        "sha256": hashlib.sha256(bundle).hexdigest(),
        "bundled_packages": record,
    }
    (_VENDOR / "plotly-cartesian.json").write_text(
        json.dumps(pin, indent=2) + "\n", encoding="utf-8"
    )
    print(f"plotly.js {version}: {len(bundle):,} bytes, {len(record)} bundled packages")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/vendor_plotly.py <plotly.js version>")
    main(sys.argv[1])
