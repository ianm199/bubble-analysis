"""Tests for routes-to functionality.

Verifies that routes-to correctly traces exceptions through call chains
back to entrypoints. This was a bug where routes-to would fail to find
connections that audit found successfully.
"""

from bubble.integrations.flask import FlaskIntegration
from bubble.integrations.queries import trace_routes_to_exception
from bubble.models import ProgramModel


class TestRoutesToTracesCallChains:
    """Test that routes-to finds exceptions that propagate through helper functions."""

    def test_routes_to_finds_indirect_exception(self, flask_model: ProgramModel) -> None:
        """Routes-to should find exceptions raised in helper functions called by routes.

        In flask_app fixture:
        - create_user() calls validate_input()
        - validate_input() raises ValidationError
        - routes-to ValidationError should find create_user route
        """
        integration = FlaskIntegration()
        entrypoints = [e for e in flask_model.entrypoints if e.kind == "http_route"]

        result = trace_routes_to_exception(
            flask_model,
            integration,
            entrypoints,
            "ValidationError",
            include_subclasses=False,
        )

        assert len(result.traces) > 0, "Should find at least one raise site"

        entrypoint_functions_found = set()
        for trace in result.traces:
            for ep in trace.entrypoints:
                entrypoint_functions_found.add(ep.function)

        assert "create_user" in entrypoint_functions_found, (
            "Should trace ValidationError back to create_user route"
        )

    def test_routes_to_finds_direct_exception(self, flask_model: ProgramModel) -> None:
        """Routes-to should also find exceptions raised directly in routes."""
        integration = FlaskIntegration()
        entrypoints = [e for e in flask_model.entrypoints if e.kind == "http_route"]

        result = trace_routes_to_exception(
            flask_model,
            integration,
            entrypoints,
            "ValidationError",
            include_subclasses=False,
        )

        entrypoint_functions_found = set()
        for trace in result.traces:
            for ep in trace.entrypoints:
                entrypoint_functions_found.add(ep.function)

        assert "get_user" in entrypoint_functions_found, (
            "Should find ValidationError raised directly in get_user route"
        )

    def test_routes_to_with_subclasses(self, flask_model: ProgramModel) -> None:
        """Routes-to should find subclasses when include_subclasses=True."""
        integration = FlaskIntegration()
        entrypoints = [e for e in flask_model.entrypoints if e.kind == "http_route"]

        result = trace_routes_to_exception(
            flask_model,
            integration,
            entrypoints,
            "AppError",
            include_subclasses=True,
        )

        assert len(result.traces) > 0, "Should find ValidationError as subclass of AppError"
        assert "ValidationError" in result.types_searched or "AppError" in result.types_searched


class TestRoutesToCLI:
    """Test routes-to via CLI."""

    def test_cli_routes_to_finds_indirect(self, flask_fixture) -> None:
        """CLI routes-to should find indirect exceptions."""
        from conftest import run_cli

        result = run_cli("flask", "routes-to", "ValidationError")
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert "create_user" in result.stdout, (
            f"Should find create_user route. Output: {result.stdout}"
        )

    def test_cli_routes_to_json_output(self, flask_fixture) -> None:
        """CLI routes-to JSON should include entrypoint info."""
        from conftest import run_cli_json

        data = run_cli_json("flask", "routes-to", "ValidationError")
        assert "results" in data

        found_create_user = False
        for result in data["results"]:
            for ep in result.get("entrypoints", []):
                if ep.get("function") == "create_user":
                    found_create_user = True

        assert found_create_user, f"Should find create_user in JSON output: {data}"
