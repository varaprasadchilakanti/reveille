# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""A recipe fails when any command in a pipe fails, or a variable is unset."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


def _make_reads_shellflags() -> bool:
    """Return whether `make` is GNU make 3.82 or later, the first to read `.SHELLFLAGS`."""
    if shutil.which("make") is None or shutil.which("bash") is None:
        return False
    first = subprocess.run(
        ["make", "--version"], capture_output=True, check=False, encoding="utf-8"
    ).stdout.partition("\n")[0]
    found = re.fullmatch(r"GNU Make (\d+)\.(\d+).*", first)
    return found is not None and (int(found[1]), int(found[2])) >= (3, 82)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not _make_reads_shellflags(), reason="needs bash and GNU make 3.82+ (macOS ships 3.81)"
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
