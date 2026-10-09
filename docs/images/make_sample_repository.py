# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Build the sample repository the README's screenshots are taken from.

The people are invented and their addresses are on `example.com`, reserved
for documentation, so the README shows a real Reveille report without
naming anyone real. The seed and the dates are fixed, so the same history,
and the same report under `--deterministic`, comes out every time.

Usage::

    python docs/images/make_sample_repository.py /tmp/sample-service
    cd /tmp/sample-service && reveille generate --deterministic
"""

from __future__ import annotations

import datetime
import os
import random
import subprocess
import sys
from pathlib import Path

#: Invented people and how often each commits, plus one automated account.
PEOPLE: tuple[tuple[str, str, float], ...] = (
    ("Ana Silva", "ana.silva@example.com", 0.27),
    ("Ben Okafor", "ben.okafor@example.com", 0.19),
    ("Chen Wei", "chen.wei@example.com", 0.15),
    ("Dara Kelly", "dara.kelly@example.com", 0.11),
    ("Eli Moreau", "eli.moreau@example.com", 0.08),
    ("Farah Haddad", "farah.haddad@example.com", 0.06),
    ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com", 0.14),
)

AREAS: tuple[str, ...] = (
    "src/core",
    "src/api/handlers",
    "src/api/models",
    "src/web/components",
    "docs",
    "tests/unit",
    "tests/integration",
)

START = datetime.datetime(2025, 1, 6, 9, 0, tzinfo=datetime.UTC)
DAYS = 350


def _pick(rng: random.Random) -> tuple[str, str]:
    """Choose an author, weighted by how often each commits.

    Args:
        rng: The seeded generator.

    Returns:
        The author's name and address.
    """
    roll, total = rng.random(), 0.0
    for name, email, weight in PEOPLE:
        total += weight
        if roll <= total:
            return name, email
    return PEOPLE[0][0], PEOPLE[0][1]


def build(target: Path) -> int:
    """Write the sample history into a new repository at `target`.

    Args:
        target: A directory that does not exist yet.

    Returns:
        How many commits were made.
    """
    rng = random.Random(20260930)
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
    made = 0
    for offset in range(DAYS):
        day = START + datetime.timedelta(days=offset)
        quiet = day.weekday() >= 5 or 150 <= offset < 172
        if quiet and rng.random() < 0.85:
            continue
        for _ in range(rng.choice((0, 1, 1, 2, 2, 3))):
            name, email = _pick(rng)
            if name.endswith("[bot]"):
                path = target / "package-lock.json"
                path.write_text(path.read_text() if path.exists() else "", encoding="utf-8")
                with path.open("a", encoding="utf-8") as lock:
                    lock.write("{}\n" * rng.randint(10, 300))
            else:
                area = target / rng.choice(AREAS)
                area.mkdir(parents=True, exist_ok=True)
                suffix = rng.choice((".py", ".py", ".ts", ".md", ".yml"))
                with (area / f"part{rng.randint(1, 9)}{suffix}").open("a", encoding="utf-8") as f:
                    f.write("line\n" * rng.randint(1, 160))
            made += 1
            stamp = (day + datetime.timedelta(hours=rng.randint(0, 8), minutes=made % 60)).isoformat()
            message = f"change {made}"
            if not name.endswith("[bot]") and rng.random() < 0.07:
                message += "\n\nCo-authored-by: Farah Haddad <farah.haddad@example.com>"
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": name,
                "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": email,
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_DATE": stamp,
            }
            subprocess.run(["git", "add", "-A"], cwd=target, check=True, env=env)
            subprocess.run(["git", "commit", "-qm", message], cwd=target, check=True, env=env)
    return made


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: make_sample_repository.py <new-directory>")
    print(f"{build(Path(sys.argv[1]))} commits")
