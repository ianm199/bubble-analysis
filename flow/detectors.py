"""Framework detectors for identifying entrypoints and patterns.

This module re-exports detectors from integrations for backward compatibility.
New code should import directly from flow.integrations.*.
"""

from flow.integrations.base import Entrypoint, GlobalHandler
from flow.integrations.cli_scripts.detector import (
    CLIEntrypointVisitor,
    detect_cli_entrypoints,
)
from flow.integrations.django.detector import (
    DjangoExceptionHandlerVisitor,
    DjangoViewVisitor,
    detect_django_entrypoints,
    detect_django_global_handlers,
)
from flow.integrations.django.semantics import (
    EXCEPTION_RESPONSES as DJANGO_EXCEPTION_RESPONSES,
)
from flow.integrations.fastapi.detector import (
    FastAPIExceptionHandlerVisitor,
    FastAPIRouteVisitor,
    detect_fastapi_entrypoints,
    detect_fastapi_global_handlers,
)
from flow.integrations.fastapi.semantics import (
    EXCEPTION_RESPONSES as FASTAPI_EXCEPTION_RESPONSES,
)
from flow.integrations.flask.detector import (
    FlaskErrorHandlerVisitor,
    FlaskRouteVisitor,
    detect_flask_entrypoints,
    detect_flask_global_handlers,
)
from flow.integrations.flask.semantics import (
    EXCEPTION_RESPONSES as FLASK_EXCEPTION_RESPONSES,
)

FRAMEWORK_EXCEPTION_RESPONSES: dict[str, dict[str, str]] = {
    "django": DJANGO_EXCEPTION_RESPONSES,
    "fastapi": FASTAPI_EXCEPTION_RESPONSES,
    "flask": FLASK_EXCEPTION_RESPONSES,
}


def detect_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect entrypoints in a Python source file (HTTP routes and CLI scripts)."""
    entrypoints: list[Entrypoint] = []
    entrypoints.extend(detect_flask_entrypoints(source, file_path))
    entrypoints.extend(detect_fastapi_entrypoints(source, file_path))
    entrypoints.extend(detect_django_entrypoints(source, file_path))
    entrypoints.extend(detect_cli_entrypoints(source, file_path))
    return entrypoints


def detect_global_handlers(source: str, file_path: str) -> list[GlobalHandler]:
    """Detect global exception handlers in a Python source file."""
    handlers: list[GlobalHandler] = []
    handlers.extend(detect_flask_global_handlers(source, file_path))
    handlers.extend(detect_fastapi_global_handlers(source, file_path))
    handlers.extend(detect_django_global_handlers(source, file_path))
    return handlers


__all__ = [
    "FRAMEWORK_EXCEPTION_RESPONSES",
    "FlaskRouteVisitor",
    "FlaskErrorHandlerVisitor",
    "FastAPIRouteVisitor",
    "FastAPIExceptionHandlerVisitor",
    "DjangoViewVisitor",
    "DjangoExceptionHandlerVisitor",
    "CLIEntrypointVisitor",
    "detect_entrypoints",
    "detect_global_handlers",
]
