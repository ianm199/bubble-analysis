"""Tests for raise site detection."""


def test_finds_direct_raises(flask_model):
    """Finds locations where ValidationError is raised."""
    matches = [r for r in flask_model.raise_sites if r.exception_type == "ValidationError"]

    assert len(matches) == 2
    functions = {r.function for r in matches}
    assert functions == {"validate_input", "get_user"}


def test_raise_site_has_location(flask_model):
    """Raise sites include file and line information."""
    for site in flask_model.raise_sites:
        assert site.file
        assert site.line > 0
        assert site.function


def test_raise_site_has_code(flask_model):
    """Raise sites include the source code."""
    for site in flask_model.raise_sites:
        assert "raise" in site.code.lower()


def test_finds_subclasses_via_hierarchy(flask_model):
    """Can find raises of subclasses via exception hierarchy."""
    subclasses = flask_model.exception_hierarchy.get_subclasses("AppError")

    assert "ValidationError" in subclasses
    assert "NotFoundError" in subclasses


def test_no_matches_for_unknown(flask_model):
    """Returns empty for non-existent exception."""
    matches = [r for r in flask_model.raise_sites if r.exception_type == "KeyError"]
    assert matches == []


def test_httpexception_in_fastapi(fastapi_model):
    """Finds HTTPException raises in FastAPI app."""
    matches = [r for r in fastapi_model.raise_sites if r.exception_type == "HTTPException"]

    assert len(matches) >= 2
    functions = {r.function for r in matches}
    assert "get_current_user" in functions
    assert "get_item" in functions
