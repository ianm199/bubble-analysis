"""CLI scripts integration for flow analysis.

Detects if __name__ == "__main__" blocks as entrypoints.
"""

import typer

from flow.integrations.base import Entrypoint, GlobalHandler
from flow.integrations.cli_scripts.detector import (
    CLIEntrypointVisitor,
    detect_cli_entrypoints,
)
from flow.integrations.models import IntegrationData


class CLIScriptsIntegration:
    """CLI scripts integration (if __name__ == "__main__")."""

    @property
    def name(self) -> str:
        return "cli"

    @property
    def cli_app(self) -> typer.Typer:
        from flow.integrations.cli_scripts.cli import app

        return app

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        return detect_cli_entrypoints(source, file_path)

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        return []

    def get_exception_response(self, exception_type: str) -> str | None:
        return None

    def extract_integration_data(self, source: str, file_path: str) -> IntegrationData:
        return IntegrationData(
            entrypoints=self.detect_entrypoints(source, file_path),
            global_handlers=[],
        )


__all__ = [
    "CLIScriptsIntegration",
    "CLIEntrypointVisitor",
    "detect_cli_entrypoints",
]
