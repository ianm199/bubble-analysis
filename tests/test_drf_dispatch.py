"""Tests for DRF class-based view dispatch injection.

Verifies that synthetic call edges are created from DRF view classes
to their HTTP method handlers (get, post, list, create, etc.).
"""

from pathlib import Path

from flow.enums import ResolutionKind
from flow.extractor import extract_from_directory
from flow.integrations.django import DjangoIntegration
from flow.integrations.queries import trace_routes_to_exception

FIXTURES = Path(__file__).parent / "fixtures"


class TestDRFDispatchInjection:
    """Tests for implicit dispatch call edge injection."""

    def test_apiview_has_dispatch_edges(self):
        """APIView class has edges to get and post methods."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        dispatch_calls = [
            c for c in model.call_sites if c.resolution_kind == ResolutionKind.IMPLICIT_DISPATCH
        ]

        caller_callee_pairs = {(c.caller_function, c.callee_name) for c in dispatch_calls}

        assert ("UserAPIView", "get") in caller_callee_pairs
        assert ("UserAPIView", "post") in caller_callee_pairs

    def test_viewset_has_action_edges(self):
        """ViewSet class has edges to DRF action methods."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        dispatch_calls = [
            c for c in model.call_sites if c.resolution_kind == ResolutionKind.IMPLICIT_DISPATCH
        ]

        caller_callee_pairs = {(c.caller_function, c.callee_name) for c in dispatch_calls}

        assert ("ItemViewSet", "list") in caller_callee_pairs
        assert ("ItemViewSet", "retrieve") in caller_callee_pairs
        assert ("ItemViewSet", "create") in caller_callee_pairs

    def test_dispatch_edges_have_qualified_names(self):
        """Dispatch edges have proper qualified caller/callee names."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        user_view_dispatch = [
            c
            for c in model.call_sites
            if c.resolution_kind == ResolutionKind.IMPLICIT_DISPATCH
            and c.caller_function == "UserAPIView"
            and c.callee_name == "get"
        ]

        assert len(user_view_dispatch) == 1
        edge = user_view_dispatch[0]

        assert "UserAPIView" in edge.caller_qualified
        assert "UserAPIView.get" in edge.callee_qualified

    def test_non_http_methods_not_injected(self):
        """Helper methods are not added as dispatch edges."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        dispatch_calls = [
            c for c in model.call_sites if c.resolution_kind == ResolutionKind.IMPLICIT_DISPATCH
        ]

        callee_names = {c.callee_name for c in dispatch_calls}

        assert "validate_request" not in callee_names
        assert "process_data" not in callee_names
        assert "get_items" not in callee_names
        assert "validate_item" not in callee_names

    def test_dispatch_edges_are_method_calls(self):
        """All dispatch edges are marked as method calls."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        dispatch_calls = [
            c for c in model.call_sites if c.resolution_kind == ResolutionKind.IMPLICIT_DISPATCH
        ]

        assert all(c.is_method_call for c in dispatch_calls)


class TestDRFRoutesToException:
    """Tests that routes-to traces through DRF class-based views."""

    def test_routes_to_finds_exception_in_view_method(self):
        """ValueError in validate_request connects to UserAPIView entrypoint."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        django_entrypoints = [
            e for e in model.entrypoints if e.metadata.get("framework") == "django"
        ]

        integration = DjangoIntegration()
        result = trace_routes_to_exception(model, integration, django_entrypoints, "ValueError")

        traces_with_entrypoints = [t for t in result.traces if t.entrypoints]
        assert len(traces_with_entrypoints) >= 2

        entrypoint_names = set()
        for trace in traces_with_entrypoints:
            for ep in trace.entrypoints:
                entrypoint_names.add(ep.function)

        assert "UserAPIView" in entrypoint_names
        assert "ItemViewSet" in entrypoint_names

    def test_routes_to_keyerror_finds_viewset(self):
        """KeyError in get_item connects to ItemViewSet entrypoint."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        django_entrypoints = [
            e for e in model.entrypoints if e.metadata.get("framework") == "django"
        ]

        integration = DjangoIntegration()
        result = trace_routes_to_exception(model, integration, django_entrypoints, "KeyError")

        traces_with_entrypoints = [t for t in result.traces if t.entrypoints]
        assert len(traces_with_entrypoints) >= 1

        entrypoint_names = {ep.function for t in traces_with_entrypoints for ep in t.entrypoints}
        assert "ItemViewSet" in entrypoint_names

    def test_routes_to_lookuperror_finds_keyerror_via_hierarchy(self):
        """LookupError -s search finds KeyError via built-in exception hierarchy."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        django_entrypoints = [
            e for e in model.entrypoints if e.metadata.get("framework") == "django"
        ]

        integration = DjangoIntegration()
        result = trace_routes_to_exception(
            model, integration, django_entrypoints, "LookupError", include_subclasses=True
        )

        assert "KeyError" in result.types_searched
        traces_with_entrypoints = [t for t in result.traces if t.entrypoints]
        assert len(traces_with_entrypoints) >= 1

    def test_routes_to_exception_finds_all_via_hierarchy(self):
        """Exception -s search finds all exceptions via built-in hierarchy."""
        model = extract_from_directory(FIXTURES / "drf_app", use_cache=False)

        django_entrypoints = [
            e for e in model.entrypoints if e.metadata.get("framework") == "django"
        ]

        integration = DjangoIntegration()
        result = trace_routes_to_exception(
            model, integration, django_entrypoints, "Exception", include_subclasses=True
        )

        assert "ValueError" in result.types_searched
        assert "KeyError" in result.types_searched

        traces_with_entrypoints = [t for t in result.traces if t.entrypoints]
        assert len(traces_with_entrypoints) >= 4
