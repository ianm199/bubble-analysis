"""Django framework integration for flow analysis."""

import typer

from flow.integrations.base import Entrypoint, GlobalHandler
from flow.integrations.django.detector import (
    DjangoExceptionHandlerVisitor,
    DjangoFunctionViewVisitor,
    DjangoURLPatternVisitor,
    DjangoViewVisitor,
    detect_django_entrypoints,
    detect_django_global_handlers,
    detect_django_url_patterns,
)
from flow.integrations.django.semantics import EXCEPTION_RESPONSES
from flow.integrations.models import IntegrationData


class DjangoIntegration:
    """Django framework integration."""

    @property
    def name(self) -> str:
        return "django"

    @property
    def cli_app(self) -> typer.Typer:
        from flow.integrations.django.cli import app

        return app

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        return detect_django_entrypoints(source, file_path)

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        return detect_django_global_handlers(source, file_path)

    def get_exception_response(self, exception_type: str) -> str | None:
        exc_simple = exception_type.split(".")[-1]
        for handled_type, response in EXCEPTION_RESPONSES.items():
            handled_simple = handled_type.split(".")[-1]
            if exc_simple == handled_simple or exception_type == handled_type:
                return response
        return None

    def extract_integration_data(self, source: str, file_path: str) -> IntegrationData:
        return IntegrationData(
            entrypoints=self.detect_entrypoints(source, file_path),
            global_handlers=self.detect_global_handlers(source, file_path),
        )


__all__ = [
    "DjangoIntegration",
    "DjangoViewVisitor",
    "DjangoFunctionViewVisitor",
    "DjangoURLPatternVisitor",
    "DjangoExceptionHandlerVisitor",
    "EXCEPTION_RESPONSES",
    "detect_django_entrypoints",
    "detect_django_global_handlers",
    "detect_django_url_patterns",
]
