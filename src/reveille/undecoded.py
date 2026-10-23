# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

r"""Write the bytes Git gave that are not UTF-8 as `\xNN`, in JSON as in text.

Git's output is read with `surrogateescape`, so each such byte is a lone
surrogate. JSON can carry one only as a `\udcNN` escape, which a strict parser
refuses. Standard library only.
"""

from __future__ import annotations

import json
import re
from typing import Any

# The bytes `surrogateescape` maps (U+DC80 to U+DCFF), then any other lone surrogate.
_UNDECODED = re.compile("[\ud800-\udfff]")


def _escape(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code - 0xDC00:02x}" if 0xDC80 <= code <= 0xDCFF else f"\\u{code:04x}"


def as_escapes(value: Any) -> Any:
    r"""Return `value` with each lone surrogate in its strings written as an escape.

    Args:
        value: A string, or a JSON document of dicts, lists and scalars.

    Returns:
        The same shape, with `\xNN` for an undecoded byte, as text output writes it.
    """
    if isinstance(value, str):
        return _UNDECODED.sub(_escape, value)
    if isinstance(value, dict):
        return {as_escapes(key): as_escapes(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [as_escapes(item) for item in value]
    return value


def json_text(document: Any, **options: Any) -> str:
    """Serialise `document` as JSON with no lone surrogate in it.

    Args:
        document: The document.
        **options: As for `json.dumps`.

    Returns:
        The JSON text.
    """
    text = json.dumps(document, **options)
    # With `ensure_ascii`, a lone surrogate can only appear as this escape.
    return json.dumps(as_escapes(document), **options) if "\\ud" in text else text
