"""Tests for exception hierarchy detection."""


def test_finds_exception_classes(hierarchy_model):
    """Finds all exception classes."""
    classes = hierarchy_model.exception_hierarchy.classes

    assert "BaseAppError" in classes
    assert "ClientError" in classes
    assert "ValidationError" in classes
    assert "AuthError" in classes
    assert "ServerError" in classes
    assert "DatabaseError" in classes


def test_hierarchy_inheritance(hierarchy_model):
    """Correctly tracks inheritance relationships."""
    hierarchy = hierarchy_model.exception_hierarchy

    assert hierarchy.is_subclass_of("ValidationError", "ClientError")
    assert hierarchy.is_subclass_of("ValidationError", "BaseAppError")
    assert hierarchy.is_subclass_of("DatabaseError", "ServerError")
    assert hierarchy.is_subclass_of("DatabaseError", "BaseAppError")

    assert not hierarchy.is_subclass_of("ValidationError", "ServerError")
    assert not hierarchy.is_subclass_of("ClientError", "ServerError")


def test_get_subclasses(hierarchy_model):
    """Gets all subclasses of a base exception."""
    hierarchy = hierarchy_model.exception_hierarchy
    subclasses = hierarchy.get_subclasses("BaseAppError")

    assert "ClientError" in subclasses
    assert "ServerError" in subclasses
    assert "ValidationError" in subclasses
    assert "AuthError" in subclasses
    assert "DatabaseError" in subclasses


def test_flask_app_exceptions(flask_model):
    """Works on flask_app fixture."""
    classes = flask_model.exception_hierarchy.classes

    assert "AppError" in classes
    assert "ValidationError" in classes
    assert "NotFoundError" in classes


def test_no_custom_exceptions(cli_model):
    """Handles codebase with no custom exception classes."""
    classes = cli_model.exception_hierarchy.classes
    assert len(classes) == 0
