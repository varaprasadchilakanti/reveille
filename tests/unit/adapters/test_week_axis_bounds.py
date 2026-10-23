# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""The weekly charts stay inside the dates Python can hold, at both ends of the calendar."""

from __future__ import annotations

import datetime

import pytest

from reveille.adapters.renderer import _week_axis, _week_starts

pytestmark = pytest.mark.unit


def test_the_weeks_stop_at_the_last_monday_a_date_can_hold() -> None:
    weeks = _week_starts(datetime.date(9999, 12, 20), datetime.date.max, [])

    assert weeks == ["9999-12-20", "9999-12-27"]


@pytest.mark.parametrize(
    ("week", "expected"),
    [
        ("2026-10-19", ["2026-10-12", "2026-10-26"]),
        ("9999-12-27", ["9999-12-20", "9999-12-31"]),
        ("0001-01-01", ["0001-01-01", "0001-01-08"]),
    ],
)
def test_one_week_is_padded_without_leaving_the_calendar(week: str, expected: list[str]) -> None:
    assert _week_axis([week])["range"] == expected
