"""Custom exceptions for Flask-AppBuilder app."""


class AppError(Exception):
    """Base application error."""


class ValidationError(AppError):
    """Validation failed."""


class DatabaseError(AppError):
    """Database operation failed."""
