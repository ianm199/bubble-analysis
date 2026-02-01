"""Tests for Flask-AppBuilder @expose decorator detection."""


def test_finds_expose_routes(flask_appbuilder_model):
    """Finds Flask-AppBuilder @expose routes."""
    http_routes = [e for e in flask_appbuilder_model.entrypoints if e.kind == "http_route"]

    assert len(http_routes) == 5
    functions = {e.function for e in http_routes}
    assert functions == {"get", "get_connection", "test_connection", "index", "stats"}


def test_expose_route_metadata(flask_appbuilder_model):
    """Flask-AppBuilder @expose routes have correct metadata."""
    routes = {e.function: e for e in flask_appbuilder_model.entrypoints}

    get_route = routes["get"]
    assert get_route.metadata.get("http_method") == "GET"
    assert get_route.metadata.get("http_path") == "/<int:pk>"

    test_conn = routes["test_connection"]
    assert test_conn.metadata.get("http_method") == "POST"
    assert test_conn.metadata.get("http_path") == "/test_connection/"

    index_route = routes["index"]
    assert index_route.metadata.get("http_method") == "GET"
    assert index_route.metadata.get("http_path") == "/"


def test_expose_with_multiple_methods(flask_appbuilder_model):
    """Handles @expose with multiple HTTP methods."""
    routes = {e.function: e for e in flask_appbuilder_model.entrypoints}

    stats_route = routes["stats"]
    assert stats_route.metadata.get("http_path") == "/stats"
