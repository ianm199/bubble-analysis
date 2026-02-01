"""Tests for generic exception handler detection."""

from flow.integrations import get_integration_by_name, load_builtin_integrations
from flow.integrations.queries import audit_integration


def test_generic_handler_detected(generic_handler_model):
    """Generic Exception handler is detected."""
    handlers = generic_handler_model.global_handlers

    generic_handlers = [h for h in handlers if h.is_generic]
    specific_handlers = [h for h in handlers if not h.is_generic]

    assert len(generic_handlers) == 1
    assert generic_handlers[0].handled_type == "Exception"
    assert len(specific_handlers) == 1
    assert specific_handlers[0].handled_type == "AppError"


def test_specific_handler_covers_subclass(generic_handler_model):
    """ValidationError (subclass of AppError) is caught by specific handler."""
    load_builtin_integrations()
    integration = get_integration_by_name("flask")
    assert integration is not None

    entrypoints = [e for e in generic_handler_model.entrypoints if e.function == "create_user"]
    handlers = generic_handler_model.global_handlers

    result = audit_integration(generic_handler_model, integration, entrypoints, handlers)

    assert result.clean_count == 1
    assert len(result.issues) == 0


def test_generic_only_exceptions_flagged(generic_handler_model):
    """UnknownError (only caught by generic handler) is flagged as an issue."""
    load_builtin_integrations()
    integration = get_integration_by_name("flask")
    assert integration is not None

    entrypoints = [e for e in generic_handler_model.entrypoints if e.function == "get_data"]
    handlers = generic_handler_model.global_handlers

    result = audit_integration(generic_handler_model, integration, entrypoints, handlers)

    assert len(result.issues) == 1
    issue = result.issues[0]
    assert "UnknownError" in issue.caught_by_generic or any(
        "UnknownError" in k for k in issue.caught_by_generic
    )
