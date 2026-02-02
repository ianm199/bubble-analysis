"""FastAPI framework integration for flow analysis."""

import typer

from bubble.integrations.base import Entrypoint, GlobalHandler
from bubble.integrations.fastapi.detector import (
    FastAPIExceptionHandlerVisitor,
    FastAPIRouteVisitor,
    detect_fastapi_entrypoints,
    detect_fastapi_global_handlers,
)
from bubble.integrations.fastapi.semantics import EXCEPTION_RESPONSES
from bubble.integrations.models import IntegrationData


class FastAPIIntegration:
    """FastAPI framework integration."""

    @property
    def name(self) -> str:
        return "fastapi"

    @property
    def cli_app(self) -> typer.Typer:
        from bubble.integrations.fastapi.cli import app

        return app

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        return detect_fastapi_entrypoints(source, file_path)

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        return detect_fastapi_global_handlers(source, file_path)

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
    "FastAPIIntegration",
    "FastAPIRouteVisitor",
    "FastAPIExceptionHandlerVisitor",
    "EXCEPTION_RESPONSES",
    "detect_fastapi_entrypoints",
    "detect_fastapi_global_handlers",
]
