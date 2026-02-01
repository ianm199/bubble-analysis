"""Custom exceptions."""


class AppError(Exception):
    """Base application error - has specific handler."""


class ValidationError(AppError):
    """Validation failed - covered by AppError handler."""


class UnknownError(Exception):
    """Unknown error - only caught by generic Exception handler."""
