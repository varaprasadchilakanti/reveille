# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`scripts/vendor_plotly.py` accepts only what it can check, offline parts tested here.

The script runs at maintainer time and downloads from the npm registry; these
tests call its checks directly, with no network.
"""

from __future__ import annotations

import base64
import hashlib
import runpy
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vendor_plotly.py"
_NAMESPACE: dict[str, Any] = runpy.run_path(str(_SCRIPT))
_DATA = b"a tarball"


def _integrity(algorithm: str) -> str:
    return f"{algorithm}-{base64.b64encode(hashlib.new(algorithm, _DATA).digest()).decode()}"


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> Any:
    function = _NAMESPACE["_verified"]
    monkeypatch.setitem(function.__globals__, "_fetch", lambda url: _DATA)
    return function


def test_a_matching_sha512_is_accepted(verified: Any) -> None:
    assert verified("https://registry.test/p.tgz", _integrity("sha512")) == _DATA


@pytest.mark.parametrize("algorithm", ["sha1", "md5", "sha256"])
def test_a_weaker_algorithm_is_refused_even_when_it_matches(verified: Any, algorithm: str) -> None:
    with pytest.raises(SystemExit, match="is not sha512"):
        verified("https://registry.test/p.tgz", _integrity(algorithm))


def test_a_mismatch_is_refused(verified: Any) -> None:
    other = base64.b64encode(hashlib.sha512(b"another").digest()).decode()

    with pytest.raises(SystemExit, match="integrity mismatch"):
        verified("https://registry.test/p.tgz", f"sha512-{other}")


def test_a_require_is_not_followed_out_of_the_source(tmp_path: Path) -> None:
    source = tmp_path / "plotly.js"
    (source / "lib").mkdir(parents=True)
    (tmp_path / "outside.js").write_text("require('evil-package');\n", encoding="utf-8")
    (source / "lib" / "index-cartesian.js").write_text(
        "require('../../outside');\nrequire('d3-format');\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit, match=r"outside the plotly\.js source"):
        _NAMESPACE["_required_packages"](source)


def test_a_require_inside_the_source_is_followed(tmp_path: Path) -> None:
    source = tmp_path / "plotly.js"
    (source / "lib").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "src" / "core.js").write_text("require('d3-format');\n", encoding="utf-8")
    (source / "lib" / "index-cartesian.js").write_text(
        "require('../src/core');\n", encoding="utf-8"
    )

    assert _NAMESPACE["_required_packages"](source) == {"d3-format": {"d3-format"}}
