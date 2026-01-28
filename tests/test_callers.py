"""Tests for caller detection."""


def test_finds_direct_callers(flask_model):
    """Finds functions that call validate_input."""
    callers = flask_model.get_callers("validate_input")

    caller_functions = {c.caller_function for c in callers}
    assert "create_user" in caller_functions


def test_no_callers(flask_model):
    """Returns empty for function with no callers."""
    callers = flask_model.get_callers("handle_app_error")
    assert callers == []


def test_call_site_has_location(flask_model):
    """Call sites include file and line information."""
    callers = flask_model.get_callers("validate_input")

    for call in callers:
        assert call.file
        assert call.line > 0


def test_cli_script_callers(cli_model):
    """Finds callers in CLI script fixture."""
    callers = cli_model.get_callers("process_data")

    caller_functions = {c.caller_function for c in callers}
    assert "main" in caller_functions
