"""Flask framework integration for flow analysis."""

import typer

from flow.integrations.base import Entrypoint, GlobalHandler
from flow.integrations.flask.detector import (
    FlaskErrorHandlerVisitor,
    FlaskRouteVisitor,
    detect_flask_entrypoints,
    detect_flask_global_handlers,
)
from flow.integrations.flask.semantics import EXCEPTION_RESPONSES
from flow.integrations.models import IntegrationData


class FlaskIntegration:
    """Flask framework integration."""

    @property
    def name(self) -> str:
        return "flask"

    @property
    def cli_app(self) -> typer.Typer:
        from flow.integrations.flask.cli import app

        return app

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        return detect_flask_entrypoints(source, file_path)

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        return detect_flask_global_handlers(source, file_path)

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
    "FlaskIntegration",
    "FlaskRouteVisitor",
    "FlaskErrorHandlerVisitor",
    "EXCEPTION_RESPONSES",
    "detect_flask_entrypoints",
    "detect_flask_global_handlers",
]
