"""Tests for catch site detection."""

from bubble import queries


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


class TestFlowAwareCatches:
    """Tests for flow-aware catches functionality."""

    def test_finds_catches_in_call_path(self, catches_flow_model):
        """Catches in the call path from raise site are found."""
        result = queries.find_catches(catches_flow_model, "ValidationError")

        catch_functions = {c.function for c in result.local_catches}
        assert "api_endpoint" in catch_functions

    def test_excludes_catches_not_in_call_path(self, catches_flow_model):
        """Catches NOT in the call path are excluded."""
        result = queries.find_catches(catches_flow_model, "ValidationError")

        catch_functions = {c.function for c in result.local_catches}
        assert "unrelated_function" not in catch_functions

    def test_no_catches_when_exception_not_raised(self, catches_flow_model):
        """No catches returned when exception is never raised."""
        result = queries.find_catches(catches_flow_model, "UnusedException")

        assert len(result.local_catches) == 0
        assert result.raise_site_count == 0

    def test_raise_site_count_populated(self, catches_flow_model):
        """raise_site_count reflects actual raise sites."""
        result = queries.find_catches(catches_flow_model, "ValidationError")

        assert result.raise_site_count == 1

    def test_different_exception_different_catches(self, catches_flow_model):
        """Different exceptions have different catch sites in call path."""
        validation_result = queries.find_catches(catches_flow_model, "ValidationError")
        network_result = queries.find_catches(catches_flow_model, "NetworkError")

        validation_functions = {c.function for c in validation_result.local_catches}
        network_functions = {c.function for c in network_result.local_catches}

        assert "api_endpoint" in validation_functions
        assert "api_endpoint" not in network_functions
        assert "another_unrelated" in network_functions

    def test_parent_exception_catches_child(self, catches_flow_model):
        """Catch of parent exception (ServiceError) catches child (ValidationError)."""
        result = queries.find_catches(catches_flow_model, "ValidationError")

        caught_types = set()
        for c in result.local_catches:
            caught_types.update(c.caught_types)

        assert "ValidationError" in caught_types

    def test_nonexistent_exception_returns_empty(self, catches_flow_model):
        """Exception that doesn't exist returns empty result."""
        result = queries.find_catches(catches_flow_model, "DoesNotExistError")

        assert len(result.local_catches) == 0
        assert len(result.global_handlers) == 0
        assert result.raise_site_count == 0

    def test_include_subclasses_finds_child_raises(self, catches_flow_model):
        """include_subclasses=True finds catches for parent when child is raised."""
        result = queries.find_catches(
            catches_flow_model, "ServiceError", include_subclasses=True
        )

        assert result.raise_site_count >= 1
        assert "ValidationError" in result.types_searched

    def test_broad_except_in_path_is_included(self, catches_flow_model):
        """Broad except Exception in call path is included."""
        result = queries.find_catches(catches_flow_model, "NetworkError")

        assert result.raise_site_count == 1
        catch_functions = {c.function for c in result.local_catches}
        assert "another_unrelated" in catch_functions
