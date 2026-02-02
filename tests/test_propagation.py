"""Unit tests for exception propagation algorithm.

These are the only unit tests - for the complex fixed-point iteration logic
that is hard to exercise end-to-end.
"""

from pathlib import Path

from bubble.extractor import extract_from_directory
from bubble.propagation import compute_direct_raises, propagate_exceptions

FIXTURES = Path(__file__).parent / "fixtures"


def test_direct_raises_found():
    """Direct raises are identified correctly."""
    model = extract_from_directory(FIXTURES / "flask_app", use_cache=False)

    direct = compute_direct_raises(model)

    functions_that_raise = {func for func in direct if direct[func]}
    assert "validate_input" in str(functions_that_raise)
    assert "get_user" in str(functions_that_raise)


def test_propagation_through_call():
    """Exceptions propagate through call chain."""
    model = extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)

    result = propagate_exceptions(model)

    main_exceptions = set()
    for func, exceptions in result.propagated_raises.items():
        if "main" in func:
            main_exceptions.update(exceptions)

    assert "ValueError" in main_exceptions
    assert "FileNotFoundError" in main_exceptions


def test_exception_hierarchy_subclass():
    """Exception hierarchy correctly identifies subclasses."""
    model = extract_from_directory(FIXTURES / "exception_hierarchy", use_cache=False)

    hierarchy = model.exception_hierarchy

    assert hierarchy.is_subclass_of("ValidationError", "ClientError")
    assert hierarchy.is_subclass_of("ValidationError", "BaseAppError")
    assert hierarchy.is_subclass_of("DatabaseError", "ServerError")
    assert not hierarchy.is_subclass_of("ValidationError", "ServerError")


def test_get_subclasses():
    """Get all subclasses of a base exception."""
    model = extract_from_directory(FIXTURES / "exception_hierarchy", use_cache=False)

    hierarchy = model.exception_hierarchy
    subclasses = hierarchy.get_subclasses("BaseAppError")

    assert "ClientError" in subclasses
    assert "ServerError" in subclasses
    assert "ValidationError" in subclasses
    assert "AuthError" in subclasses
    assert "DatabaseError" in subclasses
