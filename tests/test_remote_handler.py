"""Tests for remote handler detection in audit.

When a global handler (@errorhandler) is defined in a different file from
the route, the audit should flag this as 'caught_by_remote' rather than
treating it as fully covered. This helps developers understand that their
endpoint relies on handlers defined elsewhere.
"""

from bubble.integrations.flask import FlaskIntegration
from bubble.integrations.queries import audit_integration


class TestRemoteHandlerDetection:
    """Tests for detecting handlers in different files than the routes."""

    def test_catches_remote_handler(self, remote_handler_model):
        """Exceptions caught by handlers in different files are flagged."""
        integration = FlaskIntegration()
        entrypoints = [
            e
            for e in remote_handler_model.entrypoints
            if e.metadata.get("framework") == "flask"
        ]
        handlers = remote_handler_model.global_handlers

        result = audit_integration(
            remote_handler_model, integration, entrypoints, handlers
        )

        assert len(result.issues) == 2
        for issue in result.issues:
            assert "BalanceError" in issue.caught_by_remote
            assert len(issue.uncaught) == 0

    def test_same_file_handler_not_flagged(self, flask_model):
        """Handlers in the same file as routes are not flagged as remote."""
        integration = FlaskIntegration()
        entrypoints = [
            e for e in flask_model.entrypoints if e.metadata.get("framework") == "flask"
        ]
        handlers = flask_model.global_handlers

        result = audit_integration(flask_model, integration, entrypoints, handlers)

        for issue in result.issues:
            remote_exceptions = list(issue.caught_by_remote.keys())
            assert len(remote_exceptions) == 0, (
                f"Same-file handlers should not be marked as remote: {remote_exceptions}"
            )

    def test_audit_issue_structure(self, remote_handler_model):
        """AuditIssue contains all expected categories."""
        integration = FlaskIntegration()
        entrypoints = [
            e
            for e in remote_handler_model.entrypoints
            if e.metadata.get("framework") == "flask"
        ]
        handlers = remote_handler_model.global_handlers

        result = audit_integration(
            remote_handler_model, integration, entrypoints, handlers
        )

        issue = result.issues[0]
        assert hasattr(issue, "uncaught")
        assert hasattr(issue, "caught_by_generic")
        assert hasattr(issue, "caught_by_remote")
        assert hasattr(issue, "caught")
