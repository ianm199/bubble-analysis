"""Tests for entrypoint detection."""


def test_finds_flask_routes(flask_model):
    """Finds Flask HTTP routes."""
    http_routes = [e for e in flask_model.entrypoints if e.kind == "http_route"]

    assert len(http_routes) == 2
    functions = {e.function for e in http_routes}
    assert functions == {"create_user", "get_user"}


def test_flask_route_metadata(flask_model):
    """Flask routes have correct metadata."""
    routes = {e.function: e for e in flask_model.entrypoints}

    create_user = routes["create_user"]
    assert create_user.metadata.get("http_method") == "POST"
    assert create_user.metadata.get("http_path") == "/users"

    get_user = routes["get_user"]
    assert get_user.metadata.get("http_method") == "GET"
    assert "/users/" in get_user.metadata.get("http_path", "")


def test_finds_fastapi_routes(fastapi_model):
    """Finds FastAPI HTTP routes."""
    http_routes = [e for e in fastapi_model.entrypoints if e.kind == "http_route"]

    assert len(http_routes) == 2
    functions = {e.function for e in http_routes}
    assert functions == {"get_item", "create_item"}


def test_finds_cli_scripts(cli_model):
    """Finds CLI scripts with if __name__ == '__main__'."""
    cli_scripts = [e for e in cli_model.entrypoints if e.kind == "cli_script"]

    assert len(cli_scripts) == 1
    assert cli_scripts[0].function == "main"


def test_mixed_app_entrypoints(mixed_model):
    """Finds both HTTP routes and CLI scripts."""
    http_routes = [e for e in mixed_model.entrypoints if e.kind == "http_route"]
    cli_scripts = [e for e in mixed_model.entrypoints if e.kind == "cli_script"]

    assert len(http_routes) >= 1
    assert len(cli_scripts) >= 1


def test_no_entrypoints(hierarchy_model):
    """Handles codebase with no entrypoints."""
    assert len(hierarchy_model.entrypoints) == 0
