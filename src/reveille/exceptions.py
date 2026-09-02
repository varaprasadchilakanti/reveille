# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Domain-specific exception hierarchy for Reveille.

All exceptions raised by Reveille's public interface are subclasses of
ReveilleError. Catch that class to handle any Reveille-originated failure
generically, or catch a specific subclass for targeted handling.

The hierarchy is::

    ReveilleError
    ├── RepositoryError
    │   └── EmptyRepositoryError
    ├── ConfigurationError
    └── RenderError
        └── OutputPathError

The base class was named ``RevelleError`` — missing the second ``i`` — up to
and including v0.6.0. That spelling remains importable as a deprecated alias
and resolves to the same class, so existing ``except RevelleError`` code is
unaffected. It is scheduled for removal in v1.0.0, where the CLI contract and
public API become stable.
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
    """Base exception for all Reveille errors.

    Never raised directly. Catch this class to handle any
    Reveille-originated failure without caring about the specific cause.
    """


class RepositoryError(ReveilleError):
    """Raised when the target path is not a valid or readable Git repository.

    Covers both the case where no .git directory is present and the case
    where the repository exists but cannot be read due to permissions or
    corruption.
    """


class EmptyRepositoryError(RepositoryError):
    """Raised when no commits exist within the specified analysis window."""


class ConfigurationError(ReveilleError):
    """Raised when the supplied configuration is invalid.

    Covers malformed configuration files, invalid field values, and
    logically inconsistent date ranges where since > until.
    """


class RenderError(ReveilleError):
    """Raised when the HTML report cannot be rendered.

    Typically caused by a template error or an inability to write
    the output file to the specified path.
    """


class OutputPathError(RenderError):
    """Raised when the specified output path cannot be written.

    Caused by the parent directory not existing or by insufficient
    filesystem permissions.
    """


def __getattr__(name: str) -> type[ReveilleError]:
    """Resolve the pre-v0.7.0 misspelling of the base exception.

    PEP 562 module-level attribute access. Keeping ``RevelleError``
    importable means `except RevelleError` in existing consumer code
    continues to catch every Reveille failure, while new code and the
    warning steer callers to the corrected spelling.

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
