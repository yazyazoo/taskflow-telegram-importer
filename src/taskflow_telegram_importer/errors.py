class ImporterError(Exception):
    """Base error for expected importer failures."""


class ConfigError(ImporterError):
    """Raised when configuration or a configured secret is invalid."""
