# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Dependabot keeps the declared floors, and a local lock waits as long as Dependabot does.

Dependabot's default strategy can take the project for an app and raise every floor;
`widen` keeps them. `poetry.toml` gives `poetry lock` the same release-age window as the
pip entry's cooldown. PyYAML is not a dependency, so the YAML is read line by line.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _pip_entry() -> str:
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    entries = re.split(r"(?m)^  - package-ecosystem: ", text)
    pip = [entry for entry in entries if entry.startswith("pip\n")]
    assert len(pip) == 1, "dependabot.yml has no single pip entry"
    return pip[0]


def test_dependabot_keeps_declared_floors() -> None:
    assert re.search(r"(?m)^    versioning-strategy: widen$", _pip_entry())


def test_a_local_lock_waits_as_long_as_dependabot() -> None:
    cooldown = re.search(r"(?m)^      default-days: (\d+)$", _pip_entry())
    assert cooldown, "the pip entry has no cooldown"
    settings = tomllib.loads((_ROOT / "poetry.toml").read_text(encoding="utf-8"))

    assert settings["solver"]["min-release-age"] >= int(cooldown.group(1))
