"""Data models for framework integrations.

Contains result types shared across all integrations.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from flow.integrations.base import Entrypoint, GlobalHandler

if TYPE_CHECKING:
    from flow.models import RaiseSite


@dataclass
class IntegrationData:
    """Data extracted by a framework integration from a source file."""

    entrypoints: list[Entrypoint] = field(default_factory=list)
    global_handlers: list[GlobalHandler] = field(default_factory=list)


@dataclass
class AuditIssue:
    """An entrypoint with uncaught exceptions."""

    entrypoint: Entrypoint
    uncaught: dict[str, list["RaiseSite"]]
    caught: dict[str, list["RaiseSite"]]


@dataclass
class AuditResult:
    """Result of auditing entrypoints for a specific integration."""

    integration_name: str
    total_entrypoints: int
    issues: list[AuditIssue]
    clean_count: int


@dataclass
class EntrypointsResult:
    """Result of listing entrypoints for a specific integration."""

    integration_name: str
    entrypoints: list[Entrypoint]


@dataclass
class EntrypointTrace:
    """A single raise site traced to its entrypoints."""

    raise_site: "RaiseSite"
    paths: list[list[str]]
    entrypoints: list[Entrypoint]


@dataclass
class RoutesToResult:
    """Result of tracing which routes can reach an exception."""

    integration_name: str
    exception_type: str
    include_subclasses: bool
    types_searched: set[str]
    traces: list[EntrypointTrace]
