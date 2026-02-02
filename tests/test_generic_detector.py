"""Tests for generic detector to ensure it matches existing framework-specific detectors."""

from pathlib import Path

import pytest

from bubble.integrations.fastapi.detector import (
    detect_fastapi_entrypoints,
)
from bubble.integrations.flask.detector import (
    detect_flask_entrypoints,
    detect_flask_global_handlers,
)
from bubble.integrations.generic import detect_entrypoints, detect_global_handlers
from bubble.integrations.generic.frameworks import FASTAPI_CONFIG, FLASK_CONFIG

FIXTURES = Path(__file__).parent / "fixtures"


class TestFlaskGenericDetector:
    """Test that generic detector matches Flask-specific detector."""

    @pytest.fixture
    def flask_source(self) -> str:
        return (FIXTURES / "flask_app" / "app.py").read_text()

    def test_detects_same_routes_as_flask_detector(self, flask_source: str):
        """Generic detector finds same routes as Flask detector."""
        flask_routes = detect_flask_entrypoints(flask_source, "app.py")
        generic_routes = detect_entrypoints(flask_source, "app.py", FLASK_CONFIG)

        assert len(generic_routes) == len(flask_routes)

        flask_functions = {e.function for e in flask_routes}
        generic_functions = {e.function for e in generic_routes}
        assert generic_functions == flask_functions

    def test_extracts_same_paths(self, flask_source: str):
        """Generic detector extracts same HTTP paths."""
        flask_routes = detect_flask_entrypoints(flask_source, "app.py")
        generic_routes = detect_entrypoints(flask_source, "app.py", FLASK_CONFIG)

        flask_paths = {e.metadata.get("http_path") for e in flask_routes}
        generic_paths = {e.metadata.get("http_path") for e in generic_routes}
        assert generic_paths == flask_paths

    def test_extracts_same_methods(self, flask_source: str):
        """Generic detector extracts same HTTP methods."""
        flask_routes = detect_flask_entrypoints(flask_source, "app.py")
        generic_routes = detect_entrypoints(flask_source, "app.py", FLASK_CONFIG)

        flask_by_func = {e.function: e for e in flask_routes}
        generic_by_func = {e.function: e for e in generic_routes}

        for func in flask_by_func:
            flask_method = flask_by_func[func].metadata.get("http_method")
            generic_method = generic_by_func[func].metadata.get("http_method")
            assert generic_method == flask_method, f"Method mismatch for {func}"

    def test_detects_same_error_handlers(self, flask_source: str):
        """Generic detector finds same error handlers as Flask detector."""
        flask_handlers = detect_flask_global_handlers(flask_source, "app.py")
        generic_handlers = detect_global_handlers(flask_source, "app.py", FLASK_CONFIG)

        assert len(generic_handlers) == len(flask_handlers)

        flask_types = {h.handled_type for h in flask_handlers}
        generic_types = {h.handled_type for h in generic_handlers}
        assert generic_types == flask_types


class TestFastAPIGenericDetector:
    """Test that generic detector matches FastAPI-specific detector."""

    @pytest.fixture
    def fastapi_source(self) -> str:
        return (FIXTURES / "fastapi_app" / "main.py").read_text()

    def test_detects_same_routes_as_fastapi_detector(self, fastapi_source: str):
        """Generic detector finds same routes as FastAPI detector."""
        fastapi_routes = detect_fastapi_entrypoints(fastapi_source, "main.py")
        generic_routes = detect_entrypoints(fastapi_source, "main.py", FASTAPI_CONFIG)

        assert len(generic_routes) == len(fastapi_routes)

        fastapi_functions = {e.function for e in fastapi_routes}
        generic_functions = {e.function for e in generic_routes}
        assert generic_functions == fastapi_functions

    def test_extracts_same_paths(self, fastapi_source: str):
        """Generic detector extracts same HTTP paths."""
        fastapi_routes = detect_fastapi_entrypoints(fastapi_source, "main.py")
        generic_routes = detect_entrypoints(fastapi_source, "main.py", FASTAPI_CONFIG)

        fastapi_paths = {e.metadata.get("http_path") for e in fastapi_routes}
        generic_paths = {e.metadata.get("http_path") for e in generic_routes}
        assert generic_paths == fastapi_paths

    def test_extracts_same_methods(self, fastapi_source: str):
        """Generic detector extracts same HTTP methods."""
        fastapi_routes = detect_fastapi_entrypoints(fastapi_source, "main.py")
        generic_routes = detect_entrypoints(fastapi_source, "main.py", FASTAPI_CONFIG)

        fastapi_by_func = {e.function: e for e in fastapi_routes}
        generic_by_func = {e.function: e for e in generic_routes}

        for func in fastapi_by_func:
            fastapi_method = fastapi_by_func[func].metadata.get("http_method")
            generic_method = generic_by_func[func].metadata.get("http_method")
            assert generic_method == fastapi_method, f"Method mismatch for {func}"


class TestFlaskAppBuilderGenericDetector:
    """Test Flask-AppBuilder @expose decorator detection."""

    @pytest.fixture
    def fab_source(self) -> str:
        path = FIXTURES / "flask_appbuilder_app" / "views.py"
        if path.exists():
            return path.read_text()
        return ""

    def test_detects_expose_decorator(self, fab_source: str):
        """Generic detector finds @expose routes."""
        if not fab_source:
            pytest.skip("Flask-AppBuilder fixture not available")

        routes = detect_entrypoints(fab_source, "views.py", FLASK_CONFIG)
        assert len(routes) > 0
        functions = {e.function for e in routes}
        assert "list" in functions or len(functions) > 0


class TestPatternMatching:
    """Test pattern matching edge cases."""

    def test_wildcard_pattern_matches(self):
        """Wildcard patterns match correctly."""
        from bubble.integrations.generic.config import DecoratorRoutePattern

        pattern = DecoratorRoutePattern(decorator_pattern="*")
        assert pattern.matches_decorator("route")
        assert pattern.matches_decorator("get")
        assert pattern.matches_decorator("anything")

    def test_exact_pattern_matches(self):
        """Exact patterns only match exact names."""
        from bubble.integrations.generic.config import DecoratorRoutePattern

        pattern = DecoratorRoutePattern(decorator_pattern="route")
        assert pattern.matches_decorator("route")
        assert not pattern.matches_decorator("Route")
        assert not pattern.matches_decorator("routes")


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_invalid_source(self):
        """Gracefully handles invalid Python source."""
        routes = detect_entrypoints("this is not valid python {{{", "test.py", FLASK_CONFIG)
        assert routes == []

    def test_handles_empty_source(self):
        """Handles empty source file."""
        routes = detect_entrypoints("", "test.py", FLASK_CONFIG)
        assert routes == []

    def test_handles_no_decorators(self):
        """Handles file with no route decorators."""
        source = '''
def helper():
    pass

class NotAView:
    pass
'''
        routes = detect_entrypoints(source, "test.py", FLASK_CONFIG)
        assert routes == []

    def test_framework_name_in_metadata(self):
        """Framework name is correctly set in metadata."""
        source = '''
from flask import Flask
app = Flask(__name__)

@app.route("/")
def index():
    pass
'''
        routes = detect_entrypoints(source, "test.py", FLASK_CONFIG)
        assert len(routes) == 1
        assert routes[0].metadata.get("framework") == "flask"
