"""Tests for remote handler detection in audit.

When a global handler (@errorhandler) is defined in a different file from
the route, the data is tracked in 'caught_by_remote' but not surfaced as
an issue by default (remote handlers are considered sufficient coverage).
"""

from bubble.integrations.flask import FlaskIntegration
from bubble.integrations.queries import _compute_exception_flow_for_integration, audit_integration
from bubble.propagation import propagate_exceptions


class TestRemoteHandlerDetection:
    """Tests for detecting handlers in different files than the routes."""

    def test_remote_only_endpoints_are_clean(self, remote_handler_model):
        """Endpoints with only remote handlers should not be flagged as issues."""
        integration = FlaskIntegration()
        entrypoints = [
            e for e in remote_handler_model.entrypoints if e.metadata.get("framework") == "flask"
        ]
        handlers = remote_handler_model.global_handlers

        result = audit_integration(remote_handler_model, integration, entrypoints, handlers)

        assert len(result.issues) == 0, (
            f"Remote-only handlers should not create issues, but got {len(result.issues)}"
        )
        assert result.clean_count == len(entrypoints)

    def test_remote_handler_data_tracked_internally(self, remote_handler_model):
        """Remote handler exceptions are still tracked in the flow data."""
        integration = FlaskIntegration()
        entrypoints = [
            e for e in remote_handler_model.entrypoints if e.metadata.get("framework") == "flask"
        ]
        handlers = remote_handler_model.global_handlers
        propagation = propagate_exceptions(remote_handler_model)

        for entrypoint in entrypoints:
            flow = _compute_exception_flow_for_integration(
                entrypoint.function,
                remote_handler_model,
                propagation,
                integration,
                handlers,
                entrypoint_file=entrypoint.file,
            )
            assert "BalanceError" in flow.caught_by_remote_global

    def test_same_file_handler_not_flagged_as_remote(self, flask_model):
        """Handlers in the same file as routes are not marked as remote."""
        integration = FlaskIntegration()
        entrypoints = [e for e in flask_model.entrypoints if e.metadata.get("framework") == "flask"]
        handlers = flask_model.global_handlers

        result = audit_integration(flask_model, integration, entrypoints, handlers)

        for issue in result.issues:
            remote_exceptions = list(issue.caught_by_remote.keys())
            assert len(remote_exceptions) == 0, (
                f"Same-file handlers should not be marked as remote: {remote_exceptions}"
            )
