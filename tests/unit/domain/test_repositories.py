# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The fixed rules `reveille repos` classifies a repository by (ADR 0026)."""

from __future__ import annotations

import pytest

from reveille.domain.repositories import RepositoryActivity, status_counts, status_of

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("days", "window", "expected"),
    [
        (0, 90, "active"),
        (89, 90, "active"),  # the window's first day: 90 days ending today
        (90, 90, "quiet"),
        (364, 90, "quiet"),
        (365, 90, "dormant"),
        (None, 90, "empty"),
        (400, 500, "active"),  # a window longer than a year is all active
        (500, 500, "dormant"),
    ],
)
def test_status_by_days_since_the_last_commit(days: int | None, window: int, expected: str) -> None:
    assert status_of(days, window) == expected


def test_every_status_is_counted_in_a_fixed_order() -> None:
    counts = status_counts([RepositoryActivity("a", "quiet"), RepositoryActivity("b", "quiet")])

    assert list(counts) == ["active", "quiet", "dormant", "empty", "not read"]
    assert counts["quiet"] == 2
    assert counts["active"] == 0
