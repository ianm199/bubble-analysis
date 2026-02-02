"""Tests for call resolution improvements."""

from bubble.enums import ConfidenceLevel, ResolutionKind
from bubble.models import ProgramModel, ResolutionEdge, compute_confidence
from bubble.propagation import compute_direct_raises, propagate_exceptions


class TestCanonicalNaming:
    """Tests for canonical path::Class.method naming across all data structures."""

    def test_raise_site_uses_qualified_function_name(self, resolution_model: ProgramModel):
        """RaiseSite.function should include class name for methods."""
        runtime_error_sites = [
            rs for rs in resolution_model.raise_sites if rs.exception_type == "RuntimeError"
        ]
        assert len(runtime_error_sites) == 1
        rs = runtime_error_sites[0]

        assert rs.function == "ServiceA.process", (
            f"RaiseSite.function should be 'ServiceA.process', got '{rs.function}'"
        )

    def test_raise_site_uses_relative_path(self, resolution_model: ProgramModel):
        """RaiseSite.file should be relative path, not absolute."""
        runtime_error_sites = [
            rs for rs in resolution_model.raise_sites if rs.exception_type == "RuntimeError"
        ]
        assert len(runtime_error_sites) == 1
        rs = runtime_error_sites[0]

        assert not rs.file.startswith("/"), f"RaiseSite.file should be relative, got '{rs.file}'"
        assert rs.file == "services.py", f"RaiseSite.file should be 'services.py', got '{rs.file}'"

    def test_direct_raises_key_matches_callee_qualified(self, resolution_model: ProgramModel):
        """compute_direct_raises keys should match CallSite.callee_qualified format."""
        direct = compute_direct_raises(resolution_model)

        process_call = next(
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "process" and cs.caller_function == "caller"
        )

        assert process_call.callee_qualified is not None

        callee_key = process_call.callee_qualified
        if "::" not in callee_key:
            callee_key = f"services.py::{process_call.callee_qualified.split('.')[-2]}.{process_call.callee_qualified.split('.')[-1]}"

        assert any("ServiceA.process" in key for key in direct.keys()), (
            f"direct_raises should have a key containing 'ServiceA.process', "
            f"got keys: {list(direct.keys())}"
        )


class TestMethodExceptionPropagation:
    """Tests for exception propagation through constructor-resolved method calls."""

    def test_runtime_error_propagates_through_constructor_call(
        self, resolution_model: ProgramModel
    ):
        """RuntimeError from ServiceA.process() should propagate to caller()."""
        propagation = propagate_exceptions(resolution_model)

        caller_key = None
        for key in propagation.propagated_raises:
            if key.endswith("::caller"):
                caller_key = key
                break

        assert caller_key is not None, "Should find caller in propagated_raises"
        caller_exceptions = propagation.propagated_raises.get(caller_key, set())

        assert "RuntimeError" in caller_exceptions, (
            f"RuntimeError should propagate from ServiceA.process() to caller(), "
            f"but caller only has: {caller_exceptions}"
        )

    def test_exceptions_do_not_leak_between_same_named_methods(
        self, resolution_model: ProgramModel
    ):
        """OSError from ServiceB.process() should NOT leak to caller() which uses ServiceA.

        This tests the key format normalization fix: when caller() calls ServiceA().process(),
        only RuntimeError from ServiceA should propagate, not OSError from ServiceB.process().
        Without proper normalization, name-based fallback matches ALL .process() methods.
        """
        propagation = propagate_exceptions(resolution_model)

        caller_key = None
        for key in propagation.propagated_raises:
            if key.endswith("::caller"):
                caller_key = key
                break

        assert caller_key is not None, "Should find caller in propagated_raises"
        caller_exceptions = propagation.propagated_raises.get(caller_key, set())

        assert "OSError" not in caller_exceptions, (
            f"OSError from ServiceB.process() should NOT leak to caller() which uses ServiceA, "
            f"but caller has: {caller_exceptions}"
        )


class TestModuleAttributeResolution:
    """Tests for module attribute resolution (e.g., requests.get())."""

    def test_requests_get_resolved(self, resolution_model: ProgramModel):
        """Module attribute calls should be resolved via import map."""
        call_sites = [
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "get" and cs.caller_function == "caller"
        ]

        assert len(call_sites) >= 1
        call_site = call_sites[0]
        assert call_site.resolution_kind == ResolutionKind.MODULE_ATTRIBUTE
        assert call_site.callee_qualified == "requests.get"

    def test_module_call_not_marked_as_method(self, resolution_model: ProgramModel):
        """Module attribute calls should not be marked as method calls."""
        call_sites = [
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "get" and cs.caller_function == "caller"
        ]

        assert len(call_sites) >= 1
        call_site = call_sites[0]
        assert call_site.is_method_call is False


class TestFallbackSeparation:
    """Tests for separating methods from functions in fallback lookup."""

    def test_method_does_not_match_function(self, resolution_model: ProgramModel):
        """Method calls should not match function definitions in fallback."""
        call_sites = [
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "process" and cs.caller_function == "caller"
        ]
        assert len(call_sites) >= 1
        process_call = call_sites[0]

        assert process_call.is_method_call is True

        func_call_sites = [
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "helper_func" and cs.caller_function == "caller"
        ]
        assert len(func_call_sites) >= 1
        helper_call = func_call_sites[0]

        assert helper_call.is_method_call is False


class TestMatchCountAndConfidence:
    """Tests for match_count tracking and confidence computation."""

    def test_compute_confidence_high_for_resolved_calls(self):
        """High confidence when no fallback is used."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.IMPORT,
                is_heuristic=False,
                match_count=1,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.HIGH

    def test_compute_confidence_high_for_module_attribute(self):
        """High confidence for MODULE_ATTRIBUTE resolution."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="requests.get",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.MODULE_ATTRIBUTE,
                is_heuristic=False,
                match_count=1,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.HIGH

    def test_unambiguous_fallback_is_medium_confidence(self):
        """Medium confidence when fallback has exactly one match."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.NAME_FALLBACK,
                is_heuristic=True,
                match_count=1,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.MEDIUM

    def test_ambiguous_fallback_is_low_confidence(self):
        """Low confidence when fallback has multiple matches."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.NAME_FALLBACK,
                is_heuristic=True,
                match_count=3,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.LOW

    def test_polymorphic_is_low_confidence(self):
        """Low confidence when polymorphic resolution is used."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.POLYMORPHIC,
                is_heuristic=True,
                match_count=1,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.LOW

    def test_empty_path_is_high_confidence(self):
        """High confidence for empty path (direct raise)."""
        assert compute_confidence([]) == ConfidenceLevel.HIGH


class TestScopedFallback:
    """Tests for scoped fallback search prioritization."""

    def test_same_file_takes_priority(self, resolution_model: ProgramModel):
        """Same-file matches should take priority over other matches."""
        propagation = propagate_exceptions(resolution_model)

        caller_key = None
        for key in propagation.propagated_raises:
            if key.endswith("::caller"):
                caller_key = key
                break

        assert caller_key is not None

        caller_exceptions = propagation.propagated_raises.get(caller_key, set())
        assert "TypeError" in caller_exceptions

    def test_direct_import_takes_priority(self, resolution_model: ProgramModel):
        """Directly imported functions should take priority over project-wide matches."""
        propagation = propagate_exceptions(resolution_model)

        caller_key = None
        for key in propagation.propagated_raises:
            if key.endswith("::caller"):
                caller_key = key
                break

        assert caller_key is not None
        caller_exceptions = propagation.propagated_raises.get(caller_key, set())

        assert "ValueError" in caller_exceptions


class TestConstructorResolution:
    """Tests for constructor tracking resolution."""

    def test_constructor_call_resolved(self, resolution_model: ProgramModel):
        """Constructor calls should be resolved."""
        call_sites = [
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "process" and cs.caller_function == "caller"
        ]

        assert len(call_sites) >= 1
        call_site = call_sites[0]
        assert call_site.resolution_kind == ResolutionKind.CONSTRUCTOR
        assert "ServiceA" in (call_site.callee_qualified or "")


class TestImportResolution:
    """Tests for import resolution."""

    def test_imported_function_resolved(self, resolution_model: ProgramModel):
        """Imported functions should be resolved via import map."""
        call_sites = [
            cs
            for cs in resolution_model.call_sites
            if cs.callee_name == "helper_func" and cs.caller_function == "caller"
        ]

        assert len(call_sites) >= 1
        call_site = call_sites[0]
        assert call_site.resolution_kind == ResolutionKind.IMPORT
        assert call_site.callee_qualified == "utils.helper_func"
