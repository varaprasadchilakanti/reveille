# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A recipe fails when any command in a pipe fails, or a variable is unset."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        shutil.which("make") is None or shutil.which("bash") is None, reason="needs make and bash"
    ),
]

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("recipe", ["false | true", "false; true", 'echo "$$UNSET_IN_MAKE_TEST"'])
def test_a_recipe_fails_where_sh_would_pass_it(tmp_path: Path, recipe: str) -> None:
    probe = tmp_path / "probe.mk"
    probe.write_text(f"probe:\n\t@{recipe}\n", encoding="utf-8")

    done = subprocess.run(
        ["make", "-s", "-f", str(_ROOT / "Makefile"), "-f", str(probe), "probe"],
        cwd=_ROOT,
        capture_output=True,
        check=False,
    )

    assert done.returncode != 0
