"""Tests for exception escape analysis."""

from bubble.propagation import propagate_exceptions


def test_direct_raises_escape(flask_model):
    """Direct raises are tracked in propagation."""
    result = propagate_exceptions(flask_model)

    validate_raises = set()
    for func, exceptions in result.direct_raises.items():
        if "validate_input" in func:
            validate_raises.update(exceptions)

    assert "ValidationError" in validate_raises


def test_propagation_through_call(cli_model):
    """Exceptions propagate through call chain."""
    result = propagate_exceptions(cli_model)

    main_exceptions = set()
    for func, exceptions in result.propagated_raises.items():
        if "main" in func:
            main_exceptions.update(exceptions)

    assert "ValueError" in main_exceptions
    assert "FileNotFoundError" in main_exceptions


def test_global_handlers_detected(flask_model):
    """Global error handlers are detected."""
    handlers = flask_model.global_handlers

    handler_functions = {h.function for h in handlers}
    assert "handle_app_error" in handler_functions

    handled_types = {h.handled_type for h in handlers}
    assert "AppError" in handled_types
