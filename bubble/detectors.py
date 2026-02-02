"""Framework detectors for identifying entrypoints and patterns.

This module uses the generic detector with framework-specific configurations.
The generic detector produces identical results to the old framework-specific
detectors but with a single, configurable implementation.
"""

from bubble.integrations.base import Entrypoint, GlobalHandler
from bubble.integrations.cli_scripts.detector import (
    CLIEntrypointVisitor,
    detect_cli_entrypoints,
)
from bubble.integrations.django.detector import (
    DjangoExceptionHandlerVisitor,
    DjangoViewVisitor,
    detect_django_entrypoints,
)
from bubble.integrations.django.semantics import (
    EXCEPTION_RESPONSES as DJANGO_EXCEPTION_RESPONSES,
)
from bubble.integrations.fastapi.detector import (
    FastAPIExceptionHandlerVisitor,
    FastAPIRouteVisitor,
)
from bubble.integrations.fastapi.semantics import (
    EXCEPTION_RESPONSES as FASTAPI_EXCEPTION_RESPONSES,
)
from bubble.integrations.flask.detector import (
    FlaskErrorHandlerVisitor,
    FlaskRESTfulVisitor,
    FlaskRouteVisitor,
    detect_flask_entrypoints,
)
from bubble.integrations.flask.semantics import (
    EXCEPTION_RESPONSES as FLASK_EXCEPTION_RESPONSES,
)
from bubble.integrations.generic import (
    detect_entrypoints as generic_detect_entrypoints,
)
from bubble.integrations.generic import (
    detect_global_handlers as generic_detect_global_handlers,
)
from bubble.integrations.generic.frameworks import (
    DJANGO_CONFIG,
    FASTAPI_CONFIG,
    FLASK_CONFIG,
)

FRAMEWORK_EXCEPTION_RESPONSES: dict[str, dict[str, str]] = {
    "django": DJANGO_EXCEPTION_RESPONSES,
    "fastapi": FASTAPI_EXCEPTION_RESPONSES,
    "flask": FLASK_EXCEPTION_RESPONSES,
}


def detect_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect entrypoints in a Python source file (HTTP routes and CLI scripts).

    Uses framework-specific detectors for Flask and Django (with HTTP method detection),
    the generic detector for FastAPI, plus CLI script detection.
    """
    entrypoints: list[Entrypoint] = []
    entrypoints.extend(detect_flask_entrypoints(source, file_path))
    entrypoints.extend(generic_detect_entrypoints(source, file_path, FASTAPI_CONFIG))
    entrypoints.extend(detect_django_entrypoints(source, file_path))
    entrypoints.extend(detect_cli_entrypoints(source, file_path))
    return entrypoints


def detect_global_handlers(source: str, file_path: str) -> list[GlobalHandler]:
    """Detect global exception handlers in a Python source file.

    Uses the generic detector with Flask, FastAPI, and Django configurations.
    """
    handlers: list[GlobalHandler] = []
    handlers.extend(generic_detect_global_handlers(source, file_path, FLASK_CONFIG))
    handlers.extend(generic_detect_global_handlers(source, file_path, FASTAPI_CONFIG))
    handlers.extend(generic_detect_global_handlers(source, file_path, DJANGO_CONFIG))
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
