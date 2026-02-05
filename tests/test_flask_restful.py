"""Tests for Flask-RESTful detection."""


def test_finds_flask_restful_routes(flask_restful_model):
    """Finds Flask-RESTful Resource class routes."""
    http_routes = [e for e in flask_restful_model.entrypoints if e.kind == "http_route"]

    assert len(http_routes) >= 7

    functions = {e.function for e in http_routes}
    assert "UserResource.get" in functions
    assert "UserResource.put" in functions
    assert "UserResource.delete" in functions
    assert "UserListResource.get" in functions
    assert "UserListResource.post" in functions


def test_flask_restful_route_metadata(flask_restful_model):
    """Flask-RESTful routes have correct metadata."""
    routes = {e.function: e for e in flask_restful_model.entrypoints}

    user_get = routes.get("UserResource.get")
    assert user_get is not None
    assert user_get.metadata.get("http_method") == "GET"
    assert "/api/users/" in user_get.metadata.get("http_path", "")
    assert user_get.metadata.get("flask_restful") == "true"

    user_post = routes.get("UserListResource.post")
    assert user_post is not None
    assert user_post.metadata.get("http_method") == "POST"
    assert user_post.metadata.get("http_path") == "/api/users"


def test_flask_restful_multiple_urls(flask_restful_model):
    """Handles resources registered with multiple URLs."""
    routes = [e for e in flask_restful_model.entrypoints if e.function == "QueryResource.get"]

    assert len(routes) == 3

    paths = {e.metadata.get("http_path") for e in routes}
    assert "/api/queries/<int:query_id>" in paths
    assert "/api/queries/<int:query_id>/results/<int:result_id>" in paths
    assert "/api/query_results" in paths


def test_flask_restful_custom_api_method(flask_restful_model):
    """Detects routes registered via custom API methods like add_org_resource."""
    routes = [e for e in flask_restful_model.entrypoints if "GroupResource" in e.function]

    assert len(routes) >= 2

    methods = {e.metadata.get("http_method") for e in routes}
    assert "GET" in methods
    assert "POST" in methods


def test_flask_restful_combined_with_decorator_routes(flask_model, flask_restful_model):
    """Flask-RESTful detection doesn't break regular Flask route detection."""
    flask_routes = [e for e in flask_model.entrypoints if e.kind == "http_route"]
    assert len(flask_routes) == 2

    restful_routes = [e for e in flask_restful_model.entrypoints if e.kind == "http_route"]
    assert len(restful_routes) >= 7


def test_flask_restful_crossfile_correlation(flask_restful_crossfile_model):
    """Cross-file Flask-RESTful detection correlates classes defined in one file with registrations in another."""
    routes = [e for e in flask_restful_crossfile_model.entrypoints if e.kind == "http_route"]

    functions = {e.function for e in routes}
    assert "UserResource.get" in functions
    assert "UserResource.put" in functions
    assert "UserResource.delete" in functions
    assert "GroupResource.get" in functions
    assert "GroupResource.post" in functions


def test_flask_restful_crossfile_paths(flask_restful_crossfile_model):
    """Cross-file correlation produces correct paths from registration file."""
    routes = {e.function: e for e in flask_restful_crossfile_model.entrypoints if e.kind == "http_route"}

    user_get = routes.get("UserResource.get")
    assert user_get is not None
    assert user_get.metadata.get("http_path") == "/api/users/<int:user_id>"
    assert "resources.py" in user_get.file

    group_post = routes.get("GroupResource.post")
    assert group_post is not None
    assert group_post.metadata.get("http_path") == "/api/groups/<int:group_id>"
