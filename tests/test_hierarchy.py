"""Tests for built-in exception hierarchy support.

Verifies that standard Python exceptions are recognized in the hierarchy
without needing explicit class definitions in user code.
"""

from pathlib import Path

from flow.extractor import extract_from_directory
from flow.integrations.flask import FlaskIntegration
from flow.integrations.queries import audit_integration
from flow.models import BUILTIN_EXCEPTION_HIERARCHY, ClassHierarchy

FIXTURES = Path(__file__).parent / "fixtures"


class TestBuiltinHierarchy:
    """Tests for built-in Python exception hierarchy."""

    def test_builtin_hierarchy_bootstrapped(self):
        """ClassHierarchy includes built-in exceptions on creation."""
        hierarchy = ClassHierarchy()

        assert "ValueError" in hierarchy.parent_map
        assert "Exception" in hierarchy.parent_map
        assert "KeyError" in hierarchy.parent_map

    def test_valueerror_is_subclass_of_exception(self):
        """ValueError is recognized as a subclass of Exception."""
        hierarchy = ClassHierarchy()

        assert hierarchy.is_subclass_of("ValueError", "Exception")
        assert hierarchy.is_subclass_of("ValueError", "BaseException")

    def test_keyerror_is_subclass_of_lookuperror(self):
        """KeyError → LookupError → Exception chain is correct."""
        hierarchy = ClassHierarchy()

        assert hierarchy.is_subclass_of("KeyError", "LookupError")
        assert hierarchy.is_subclass_of("KeyError", "Exception")
        assert hierarchy.is_subclass_of("LookupError", "Exception")

    def test_oserror_subclasses(self):
        """OSError subclasses (FileNotFoundError, PermissionError) are correct."""
        hierarchy = ClassHierarchy()

        assert hierarchy.is_subclass_of("FileNotFoundError", "OSError")
        assert hierarchy.is_subclass_of("PermissionError", "OSError")
        assert hierarchy.is_subclass_of("FileNotFoundError", "Exception")

    def test_notimplementederror_chain(self):
        """NotImplementedError → RuntimeError → Exception chain."""
        hierarchy = ClassHierarchy()

        assert hierarchy.is_subclass_of("NotImplementedError", "RuntimeError")
        assert hierarchy.is_subclass_of("NotImplementedError", "Exception")

    def test_get_subclasses_of_exception(self):
        """get_subclasses returns built-in exceptions."""
        hierarchy = ClassHierarchy()

        subclasses = hierarchy.get_subclasses("Exception")

        assert "ValueError" in subclasses
        assert "TypeError" in subclasses
        assert "KeyError" in subclasses
        assert "RuntimeError" in subclasses

    def test_get_subclasses_of_oserror(self):
        """get_subclasses returns OSError subclasses."""
        hierarchy = ClassHierarchy()

        subclasses = hierarchy.get_subclasses("OSError")

        assert "FileNotFoundError" in subclasses
        assert "PermissionError" in subclasses
        assert "TimeoutError" in subclasses

    def test_unrelated_exceptions_not_subclasses(self):
        """Unrelated exceptions are not subclasses of each other."""
        hierarchy = ClassHierarchy()

        assert not hierarchy.is_subclass_of("ValueError", "KeyError")
        assert not hierarchy.is_subclass_of("TypeError", "ValueError")
        assert not hierarchy.is_subclass_of("OSError", "ValueError")

    def test_baseexception_hierarchy(self):
        """BaseException subclasses include KeyboardInterrupt, SystemExit."""
        hierarchy = ClassHierarchy()

        assert hierarchy.is_subclass_of("KeyboardInterrupt", "BaseException")
        assert hierarchy.is_subclass_of("SystemExit", "BaseException")
        assert not hierarchy.is_subclass_of("KeyboardInterrupt", "Exception")

    def test_all_builtin_exceptions_have_parents(self):
        """Every built-in exception has parent_map entry."""
        hierarchy = ClassHierarchy()

        for exc_name in BUILTIN_EXCEPTION_HIERARCHY:
            assert exc_name in hierarchy.parent_map

    def test_child_map_populated(self):
        """child_map is populated correctly for built-ins."""
        hierarchy = ClassHierarchy()

        assert "ValueError" in hierarchy.child_map.get("Exception", [])
        assert "KeyError" in hierarchy.child_map.get("LookupError", [])
        assert "FileNotFoundError" in hierarchy.child_map.get("OSError", [])


class TestGlobalExceptionHandler:
    """Tests that global Exception handlers catch built-in exceptions."""

    def test_global_exception_handler_flags_generic_catches(self):
        """@errorhandler(Exception) catches ValueError but flags it as generic-only."""
        model = extract_from_directory(FIXTURES / "global_handler_app", use_cache=False)

        flask_entrypoints = [e for e in model.entrypoints if e.metadata.get("framework") == "flask"]
        flask_handlers = [h for h in model.global_handlers if "handle_all_errors" in h.function]

        integration = FlaskIntegration()
        result = audit_integration(model, integration, flask_entrypoints, flask_handlers)

        assert len(result.issues) == len(flask_entrypoints)
        for issue in result.issues:
            assert len(issue.uncaught) == 0
            assert len(issue.caught_by_generic) > 0
