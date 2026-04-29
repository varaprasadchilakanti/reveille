"""Domain-specific exception hierarchy for Reveille.

All exceptions raised by Reveille's public interface are subclasses
of RevelleError. Callers may catch RevelleError to handle any
Reveille-originated failure generically, or catch specific
subclasses for targeted error handling.
"""


class RevelleError(Exception):
    """Base exception for all Reveille errors.

    Never raised directly. Catch this class to handle any
    Reveille-originated failure without caring about the specific cause.
    """


class RepositoryError(RevelleError):
    """Raised when the target path is not a valid or readable Git repository.

    Covers both the case where no .git directory is present and the case
    where the repository exists but cannot be read due to permissions or
    corruption.
    """


class EmptyRepositoryError(RepositoryError):
    """Raised when no commits exist within the specified analysis window."""


class ConfigurationError(RevelleError):
    """Raised when the supplied configuration is invalid.

    Covers malformed configuration files, invalid field values, and
    logically inconsistent date ranges where since > until.
    """


class RenderError(RevelleError):
    """Raised when the HTML report cannot be rendered.

    Typically caused by a template error or an inability to write
    the output file to the specified path.
    """


class OutputPathError(RenderError):
    """Raised when the specified output path cannot be written to.

    Caused either by the parent directory not existing or by
    insufficient filesystem permissions.
    """
