"""Tests for catch site detection."""


def test_finds_global_handler(flask_model):
    """Finds Flask @errorhandler that catches AppError."""
    handlers = flask_model.global_handlers

    handler_functions = {h.function for h in handlers}
    assert "handle_app_error" in handler_functions


def test_global_handler_type(flask_model):
    """Global handler has correct exception type."""
    handlers = {h.function: h for h in flask_model.global_handlers}

    app_handler = handlers.get("handle_app_error")
    assert app_handler is not None
    assert app_handler.handled_type == "AppError"


def test_catch_sites_tracked(flask_model):
    """Catch sites are tracked in the model."""
    assert hasattr(flask_model, "catch_sites")


def test_no_handlers_in_cli(cli_model):
    """CLI scripts have no global handlers."""
    assert len(cli_model.global_handlers) == 0
