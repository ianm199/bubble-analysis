"""Framework integrations for flow analysis.

Each integration provides:
- Entrypoint detection (HTTP routes, CLI scripts, etc.)
- Global handler detection (error handlers)
- Exception-to-HTTP-response mappings
- CLI subcommands (flow flask audit, flow fastapi audit, etc.)
"""

from typing import TYPE_CHECKING

from bubble.integrations.base import (
    Entrypoint,
    EntrypointDetector,
    EntrypointKind,
    GlobalHandler,
    GlobalHandlerDetector,
    Integration,
)

if TYPE_CHECKING:
    from bubble.models import ProgramModel


_registered_integrations: list[Integration] = []
_builtin_integrations_loaded: bool = False


def register_integration(integration: Integration) -> None:
    """Register a framework integration."""
    _registered_integrations.append(integration)


def get_registered_integrations() -> list[Integration]:
    """Get all registered integrations."""
    return list(_registered_integrations)


def get_enabled_integrations(model: "ProgramModel") -> list[Integration]:
    """Get integrations that are enabled for a given program model.

    An integration is enabled if its framework was detected in the codebase.
    """
    enabled: list[Integration] = []
    detected = model.detected_frameworks

    for integration in _registered_integrations:
        if integration.name in detected:
            enabled.append(integration)

    return enabled


def get_integration_by_name(name: str) -> Integration | None:
    """Get an integration by name."""
    for integration in _registered_integrations:
        if integration.name == name:
            return integration
    return None


def load_builtin_integrations() -> None:
    """Load built-in integrations (only once)."""
    global _builtin_integrations_loaded
    if _builtin_integrations_loaded:
        return

    from bubble.integrations.cli_scripts import CLIScriptsIntegration
    from bubble.integrations.django import DjangoIntegration
    from bubble.integrations.fastapi import FastAPIIntegration
    from bubble.integrations.flask import FlaskIntegration

    register_integration(FlaskIntegration())
    register_integration(FastAPIIntegration())
    register_integration(DjangoIntegration())
    register_integration(CLIScriptsIntegration())
    _builtin_integrations_loaded = True


__all__ = [
    "Entrypoint",
    "EntrypointDetector",
    "EntrypointKind",
    "GlobalHandler",
    "GlobalHandlerDetector",
    "Integration",
    "register_integration",
    "get_registered_integrations",
    "get_enabled_integrations",
    "get_integration_by_name",
    "load_builtin_integrations",
]
