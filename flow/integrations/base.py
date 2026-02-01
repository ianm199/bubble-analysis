"""Base types and protocols for framework integrations.

Framework integrations detect entrypoints, global handlers, and define
how framework-specific exceptions map to HTTP responses.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import typer

from flow.enums import EntrypointKind

if TYPE_CHECKING:
    from flow.integrations.models import IntegrationData


@dataclass
class Entrypoint:
    """An entrypoint where external input enters the program."""

    file: str
    function: str
    line: int
    kind: EntrypointKind
    metadata: dict[str, str] = field(default_factory=dict)


GENERIC_EXCEPTION_TYPES = frozenset({"Exception", "BaseException"})


@dataclass
class GlobalHandler:
    """A global exception handler (e.g., Flask @errorhandler)."""

    file: str
    line: int
    function: str
    handled_type: str

    @property
    def is_generic(self) -> bool:
        """Check if this handler catches a generic exception type."""
        simple_type = self.handled_type.split(".")[-1]
        return simple_type in GENERIC_EXCEPTION_TYPES


class EntrypointDetector(Protocol):
    """Protocol for detecting entrypoints in source code."""

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect entrypoints in a Python source file."""
        ...


class GlobalHandlerDetector(Protocol):
    """Protocol for detecting global exception handlers."""

    def detect(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Detect global exception handlers in a Python source file."""
        ...


class Integration(Protocol):
    """Protocol defining a framework integration.

    Each integration provides:
    - A name used for CLI subcommands (e.g., "flask", "fastapi", "cli")
    - Detection for entrypoints and global handlers
    - Exception-to-HTTP-response mappings (for HTTP frameworks)
    - A typer app for CLI subcommands
    """

    @property
    def name(self) -> str:
        """Integration name used for CLI subcommands."""
        ...

    @property
    def cli_app(self) -> typer.Typer:
        """Typer app with CLI subcommands for this integration."""
        ...

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect entrypoints specific to this framework."""
        ...

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Detect global handlers specific to this framework."""
        ...

    def get_exception_response(self, exception_type: str) -> str | None:
        """Get HTTP response for a framework-handled exception, if any."""
        ...

    def extract_integration_data(self, source: str, file_path: str) -> "IntegrationData":
        """Extract all integration-specific data from a source file."""
        ...
