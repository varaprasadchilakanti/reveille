# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`repos` holds each warning once, however many handlers it reaches, in order."""

from __future__ import annotations

import logging

from reveille.services.report import _HeldWarnings


def test_a_record_seen_by_two_handlers_is_held_once() -> None:
    logger = logging.getLogger("reveille.test_held")
    first, second = logging.NullHandler(), logging.NullHandler()
    logger.addHandler(first)
    logging.getLogger("reveille").addHandler(second)
    held = _HeldWarnings()
    try:
        with held.installed(), held.on_this_thread() as records:
            for n in range(3):
                logger.warning("w%d", n)
    finally:
        logger.removeHandler(first)
        logging.getLogger("reveille").removeHandler(second)

    assert [r.getMessage() for r in records] == ["w0", "w1", "w2"]
