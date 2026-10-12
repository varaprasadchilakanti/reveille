# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Exception hierarchy for Reveille; every public exception is a ReveilleError.

The hierarchy is::

    ReveilleError
    ├── RepositoryError
    │   └── EmptyRepositoryError
    ├── ConfigurationError
    └── RenderError
        └── OutputPathError

``RevelleError`` remains a deprecated alias of the base class until v1.0.0.
"""

from __future__ import annotations

import warnings

__all__ = [
    "ConfigurationError",
    "EmptyRepositoryError",
    "OutputPathError",
    "RenderError",
    "RepositoryError",
    "ReveilleError",
]


class ReveilleError(Exception):
    """Base exception for all Reveille errors; never raised directly."""


class RepositoryError(ReveilleError):
    """Raised when the target path is not a valid or readable Git repository."""


class EmptyRepositoryError(RepositoryError):
    """Raised when no commits exist within the specified analysis window."""


class ConfigurationError(ReveilleError):
    """Raised for a malformed config file, invalid value, or since > until."""


class RenderError(ReveilleError):
    """Raised when the HTML report cannot be rendered or written."""


class OutputPathError(RenderError):
    """Raised when the output path cannot be written (missing parent, permissions)."""


def __getattr__(name: str) -> type[ReveilleError]:
    """Resolve the deprecated ``RevelleError`` alias (PEP 562), with a warning.

    Args:
        name: The attribute being accessed on this module.

    Returns:
        ReveilleError, when the deprecated alias is requested.

    Raises:
        AttributeError: For any other name, as normal attribute access would.
    """
    if name == "RevelleError":
        warnings.warn(
            "reveille.exceptions.RevelleError is a misspelling retained for "
            "backwards compatibility and will be removed in v1.0.0. "
            "Use ReveilleError instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ReveilleError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
