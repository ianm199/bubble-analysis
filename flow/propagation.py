"""Exception propagation analysis.

Computes which exceptions can escape from each function and entrypoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flow.stubs import StubLibrary

from flow.enums import ResolutionKind, ResolutionMode
from flow.models import (
    CallSite,
    CatchSite,
    ClassHierarchy,
    ExceptionEvidence,
    GlobalHandler,
    ProgramModel,
    RaiseSite,
    ResolutionEdge,
    compute_confidence,
)

_propagation_cache: dict[tuple[int, ResolutionMode, int | None], PropagationResult] = {}


@dataclass(frozen=True)
class PropagatedRaise:
    """A raise site propagated to a function with its call path."""

    exception_type: str
    raise_site: RaiseSite
    path: tuple[ResolutionEdge, ...]


@dataclass
class ExceptionFlow:
    """The computed exception flow for a function or entrypoint."""

    caught_locally: dict[str, list[RaiseSite]] = field(default_factory=dict)
    caught_by_global: dict[str, list[RaiseSite]] = field(default_factory=dict)
    caught_by_generic: dict[str, list[RaiseSite]] = field(default_factory=dict)
    uncaught: dict[str, list[RaiseSite]] = field(default_factory=dict)
    framework_handled: dict[str, list[tuple[RaiseSite, str]]] = field(default_factory=dict)
    evidence: dict[str, list[ExceptionEvidence]] = field(default_factory=dict)


@dataclass
class PropagationResult:
    """Results of exception propagation analysis."""

    direct_raises: dict[str, set[str]] = field(default_factory=dict)
    propagated_raises: dict[str, set[str]] = field(default_factory=dict)
    catches_by_function: dict[str, list[CatchSite]] = field(default_factory=dict)
    propagated_with_evidence: dict[str, dict[tuple[str, str, int], PropagatedRaise]] = field(
        default_factory=dict
    )


def build_forward_call_graph(model: ProgramModel) -> dict[str, set[str]]:
    """Build a map from caller to callees."""
    graph: dict[str, set[str]] = {}

    for call_site in model.call_sites:
        caller = call_site.caller_qualified or f"{call_site.file}::{call_site.caller_function}"
        callee = call_site.callee_qualified or call_site.callee_name

        if caller not in graph:
            graph[caller] = set()
        graph[caller].add(callee)

    return graph


def build_name_to_qualified(propagation: "PropagationResult") -> dict[str, list[str]]:
    """Build a map from simple function names to their qualified names."""
    name_to_qualified: dict[str, list[str]] = {}
    for key in propagation.propagated_raises:
        simple = key.split("::")[-1].split(".")[-1] if "::" in key else key.split(".")[-1]
        if simple not in name_to_qualified:
            name_to_qualified[simple] = []
        name_to_qualified[simple].append(key)
    return name_to_qualified


def build_reverse_call_graph(
    model: ProgramModel,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build maps from callee to callers (both qualified and name-based)."""
    qualified_graph: dict[str, set[str]] = {}
    name_graph: dict[str, set[str]] = {}

    for call_site in model.call_sites:
        caller = call_site.caller_qualified or call_site.caller_function

        if call_site.callee_qualified:
            if call_site.callee_qualified not in qualified_graph:
                qualified_graph[call_site.callee_qualified] = set()
            qualified_graph[call_site.callee_qualified].add(caller)

        if call_site.callee_name not in name_graph:
            name_graph[call_site.callee_name] = set()
        name_graph[call_site.callee_name].add(caller)

    return qualified_graph, name_graph


def compute_direct_raises(model: ProgramModel) -> dict[str, set[str]]:
    """Compute the set of exceptions directly raised in each function."""
    direct_raises: dict[str, set[str]] = {}

    for raise_site in model.raise_sites:
        func_key = f"{raise_site.file}::{raise_site.function}"
        if func_key not in direct_raises:
            direct_raises[func_key] = set()
        direct_raises[func_key].add(raise_site.exception_type)

    return direct_raises


def compute_catches_by_function(model: ProgramModel) -> dict[str, list[CatchSite]]:
    """Group catch sites by the function they belong to."""
    catches: dict[str, list[CatchSite]] = {}

    for catch_site in model.catch_sites:
        func_key = f"{catch_site.file}::{catch_site.function}"
        if func_key not in catches:
            catches[func_key] = []
        catches[func_key].append(catch_site)

    return catches


def expand_polymorphic_call(
    callee: str,
    hierarchy: ClassHierarchy,
    method_to_qualified: dict[str, list[str]],
) -> list[str]:
    """Expand a polymorphic method call to all concrete implementations.

    If callee is a method on an abstract class, returns qualified names of
    all concrete implementations. Otherwise returns [callee].
    """
    if "." not in callee:
        return [callee]

    parts = callee.split(".")
    if len(parts) < 2:
        return [callee]

    method_name = parts[-1]
    class_name = parts[-2] if len(parts) >= 2 else None

    if not class_name:
        return [callee]

    if not hierarchy.is_abstract_method(class_name, method_name):
        return [callee]

    implementations = hierarchy.get_concrete_implementations(class_name, method_name)
    if not implementations:
        return [callee]

    result: list[str] = []
    for impl_class, _ in implementations:
        for qualified in method_to_qualified.get(method_name, []):
            if impl_class in qualified:
                result.append(qualified)
                break
        else:
            result.append(f"{impl_class}.{method_name}")

    return result if result else [callee]


def exception_is_caught(
    exception_type: str,
    catch_site: CatchSite,
    hierarchy: ClassHierarchy,
) -> bool:
    """Check if an exception type would be caught by a catch site."""
    if catch_site.has_bare_except:
        return True

    exception_simple = exception_type.split(".")[-1]

    for caught_type in catch_site.caught_types:
        caught_simple = caught_type.split(".")[-1]

        if exception_type == caught_type or exception_simple == caught_simple:
            return True

        if caught_simple in ("Exception", "BaseException"):
            return True

        if hierarchy.is_subclass_of(exception_simple, caught_simple):
            return True

    return False


def _build_call_site_lookup(
    model: ProgramModel,
) -> dict[tuple[str, str], list[CallSite]]:
    """Build a lookup from (caller, callee) pairs to CallSite objects."""
    lookup: dict[tuple[str, str], list[CallSite]] = {}
    for cs in model.call_sites:
        caller = cs.caller_qualified or f"{cs.file}::{cs.caller_function}"
        callee = cs.callee_qualified or cs.callee_name
        key = (caller, callee)
        if key not in lookup:
            lookup[key] = []
        lookup[key].append(cs)
    return lookup


def _build_raise_site_lookup(
    model: ProgramModel,
) -> dict[tuple[str, str, int], RaiseSite]:
    """Build a lookup from (exc_type, file, line) to RaiseSite."""
    lookup: dict[tuple[str, str, int], RaiseSite] = {}
    for rs in model.raise_sites:
        lookup[(rs.exception_type, rs.file, rs.line)] = rs
    return lookup


def _create_resolution_edge(
    call_site: CallSite,
    caller: str,
    callee: str,
    used_name_fallback: bool,
    is_polymorphic: bool,
    match_count: int = 1,
) -> ResolutionEdge:
    """Create a ResolutionEdge from a CallSite."""
    if used_name_fallback:
        kind = ResolutionKind.NAME_FALLBACK
    elif is_polymorphic:
        kind = ResolutionKind.POLYMORPHIC
    else:
        kind = call_site.resolution_kind

    is_heuristic = kind in (ResolutionKind.NAME_FALLBACK, ResolutionKind.POLYMORPHIC)

    return ResolutionEdge(
        caller=caller,
        callee=callee,
        file=call_site.file,
        line=call_site.line,
        resolution_kind=kind,
        is_heuristic=is_heuristic,
        match_count=match_count,
    )


FallbackKey = tuple[str, bool]
FallbackCacheKey = tuple[str, bool, str]
_fallback_cache: dict[FallbackCacheKey, tuple[list[str], str]] = {}


def _scoped_fallback_lookup(
    callee_simple: str,
    is_method: bool,
    caller_file: str,
    import_map: dict[str, str],
    name_to_qualified: dict[FallbackKey, list[str]],
) -> tuple[list[str], str]:
    """Scoped fallback: same_file > direct_import > same_package > project."""
    cache_key: FallbackCacheKey = (callee_simple, is_method, caller_file)
    if cache_key in _fallback_cache:
        return _fallback_cache[cache_key]

    fallback_key = (callee_simple, is_method)
    candidates = name_to_qualified.get(fallback_key, [])

    if not candidates:
        result = ([], "none")
        _fallback_cache[cache_key] = result
        return result

    same_file = [c for c in candidates if c.startswith(f"{caller_file}::")]
    if same_file:
        result = (same_file, "same_file")
        _fallback_cache[cache_key] = result
        return result

    imported_modules = set(import_map.values())
    direct_imports = [c for c in candidates if any(c.startswith(mod) for mod in imported_modules)]
    if direct_imports:
        result = (direct_imports, "direct_import")
        _fallback_cache[cache_key] = result
        return result

    caller_dir = "/".join(caller_file.split("/")[:-1]) if "/" in caller_file else ""
    if caller_dir:
        same_package = [c for c in candidates if c.split("::")[0].startswith(caller_dir + "/")]
        if same_package:
            result = (same_package, "same_package")
            _fallback_cache[cache_key] = result
            return result

    result = (candidates, "project")
    _fallback_cache[cache_key] = result
    return result


def propagate_exceptions(
    model: ProgramModel,
    max_iterations: int = 100,
    resolution_mode: ResolutionMode = ResolutionMode.DEFAULT,
    stub_library: StubLibrary | None = None,
) -> PropagationResult:
    """
    Propagate exceptions through the call graph.

    For each function, compute the set of exceptions that can escape from it,
    taking into account what it catches.

    Resolution modes:
    - strict: Only follow resolved calls (no name_fallback or polymorphic)
    - default: Normal propagation with name fallback
    - aggressive: Include fuzzy matching (not yet implemented)
    """
    from flow import timing

    cache_key = (id(model), resolution_mode, id(stub_library) if stub_library else None)

    if cache_key in _propagation_cache:
        return _propagation_cache[cache_key]

    with timing.timed("propagation_setup"):
        direct_raises = compute_direct_raises(model)
        catches_by_function = compute_catches_by_function(model)
        forward_graph = build_forward_call_graph(model)
        call_site_lookup = _build_call_site_lookup(model)

    propagated: dict[str, set[str]] = {}
    propagated_evidence: dict[str, dict[tuple[str, str, int], PropagatedRaise]] = {}

    for func, raises in direct_raises.items():
        propagated[func] = raises.copy()
        propagated_evidence[func] = {}
        for exc_type in raises:
            for rs in model.raise_sites:
                if f"{rs.file}::{rs.function}" == func and rs.exception_type == exc_type:
                    key = (exc_type, rs.file, rs.line)
                    propagated_evidence[func][key] = PropagatedRaise(
                        exception_type=exc_type,
                        raise_site=rs,
                        path=(),
                    )

    name_to_qualified: dict[FallbackKey, list[str]] = {}
    method_to_qualified: dict[str, list[str]] = {}
    for qualified_key in propagated:
        simple_name = qualified_key.split("::")[-1].split(".")[-1]
        is_method = "." in qualified_key.split("::")[-1] if "::" in qualified_key else False
        fallback_key: FallbackKey = (simple_name, is_method)
        if fallback_key not in name_to_qualified:
            name_to_qualified[fallback_key] = []
        name_to_qualified[fallback_key].append(qualified_key)

        if "::" in qualified_key:
            method_name = qualified_key.split("::")[-1].split(".")[-1]
            if method_name not in method_to_qualified:
                method_to_qualified[method_name] = []
            method_to_qualified[method_name].append(qualified_key)

    with timing.timed("propagation_fixpoint"):
        iteration_count = 0
        total_fallback_lookups = 0
        total_catch_checks = 0
        total_propagations = 0

        for _ in range(max_iterations):
            iteration_count += 1
            changed = False

            for caller, callees in forward_graph.items():
                if caller not in propagated:
                    propagated[caller] = set()
                if caller not in propagated_evidence:
                    propagated_evidence[caller] = {}

                for callee in callees:
                    call_sites = call_site_lookup.get((caller, callee), [])
                    call_site = call_sites[0] if call_sites else None
                    expanded_callees = expand_polymorphic_call(
                        callee, model.exception_hierarchy, method_to_qualified
                    )
                    is_polymorphic = len(expanded_callees) > 1

                    for expanded_callee in expanded_callees:
                        used_name_fallback = False
                        fallback_match_count = 1
                        callee_exceptions = propagated.get(expanded_callee, set())
                        callee_evidence = propagated_evidence.get(expanded_callee, {})

                        if not callee_exceptions:
                            callee_simple = (
                                expanded_callee.split("::")[-1].split(".")[-1]
                                if "::" in expanded_callee
                                else expanded_callee.split(".")[-1]
                            )
                            is_method = call_site.is_method_call if call_site else False
                            caller_file = caller.split("::")[0] if "::" in caller else caller
                            import_map = model.import_maps.get(caller_file, {})

                            total_fallback_lookups += 1
                            matched_keys, _ = _scoped_fallback_lookup(
                                callee_simple,
                                is_method,
                                caller_file,
                                import_map,
                                name_to_qualified,
                            )
                            fallback_match_count = len(matched_keys) if matched_keys else 1

                            for qualified_key in matched_keys:
                                callee_exceptions = callee_exceptions | propagated.get(
                                    qualified_key, set()
                                )
                                callee_evidence = {
                                    **callee_evidence,
                                    **propagated_evidence.get(qualified_key, {}),
                                }
                                if callee_exceptions:
                                    used_name_fallback = True

                        if stub_library and not callee_exceptions:
                            callee_parts = expanded_callee.split(".")
                            if len(callee_parts) >= 2:
                                module = callee_parts[0]
                                func = callee_parts[-1]
                                stub_exceptions = stub_library.get_raises(module, func)
                                if stub_exceptions:
                                    callee_exceptions = set(stub_exceptions)

                        if resolution_mode == ResolutionMode.STRICT and (
                            used_name_fallback or is_polymorphic
                        ):
                            continue

                        for exc_type in callee_exceptions:
                            catches = catches_by_function.get(caller, [])
                            is_caught = False

                            for catch_site in catches:
                                total_catch_checks += 1
                                if exception_is_caught(
                                    exc_type, catch_site, model.exception_hierarchy
                                ):
                                    if not catch_site.has_reraise:
                                        is_caught = True
                                        break

                            if not is_caught and exc_type not in propagated[caller]:
                                propagated[caller].add(exc_type)
                                total_propagations += 1
                                changed = True

                                caller_simple = (
                                    caller.split("::")[-1].split(".")[-1]
                                    if "::" in caller
                                    else caller
                                )
                                caller_is_method = (
                                    "." in caller.split("::")[-1] if "::" in caller else False
                                )
                                caller_fallback_key: FallbackKey = (
                                    caller_simple,
                                    caller_is_method,
                                )
                                if caller_fallback_key not in name_to_qualified:
                                    name_to_qualified[caller_fallback_key] = []
                                if caller not in name_to_qualified[caller_fallback_key]:
                                    name_to_qualified[caller_fallback_key].append(caller)

                            if not is_caught:
                                for key, prop_raise in callee_evidence.items():
                                    if key[0] != exc_type:
                                        continue
                                    if key in propagated_evidence[caller]:
                                        continue
                                    if call_site is None:
                                        continue
                                    edge = _create_resolution_edge(
                                        call_site,
                                        caller,
                                        expanded_callee,
                                        used_name_fallback,
                                        is_polymorphic,
                                        fallback_match_count,
                                    )
                                    new_path = (edge,) + prop_raise.path
                                    propagated_evidence[caller][key] = PropagatedRaise(
                                        exception_type=exc_type,
                                        raise_site=prop_raise.raise_site,
                                        path=new_path,
                                    )

            if not changed:
                break

        if timing.is_enabled():
            timing.record_count("propagation_iterations", iteration_count)
            timing.record_count("propagation_fallback_lookups", total_fallback_lookups)
            timing.record_count("propagation_catch_checks", total_catch_checks)
            timing.record_count("propagation_new_exceptions", total_propagations)
            timing.record_count("propagation_call_graph_size", len(forward_graph))
            timing.record_count("propagation_functions_with_raises", len(propagated))

    result = PropagationResult(
        direct_raises=direct_raises,
        propagated_raises=propagated,
        catches_by_function=catches_by_function,
        propagated_with_evidence=propagated_evidence,
    )

    _propagation_cache[cache_key] = result
    return result


def clear_propagation_cache() -> None:
    """Clear the propagation cache.

    Call this when memory management is needed or in tests to ensure
    fresh propagation results.
    """
    _propagation_cache.clear()
    _fallback_cache.clear()


def compute_reachable_functions(
    start_func: str,
    model: ProgramModel,
    propagation: PropagationResult,
    forward_graph: dict[str, set[str]] | None = None,
    name_to_qualified: dict[str, list[str]] | None = None,
) -> set[str]:
    """Compute all functions reachable from a starting function via the call graph.

    For better performance when calling repeatedly, pre-compute forward_graph and
    name_to_qualified once and pass them in.
    """
    if forward_graph is None:
        forward_graph = build_forward_call_graph(model)

    if name_to_qualified is None:
        name_to_qualified = {}
        for key in propagation.propagated_raises:
            simple = key.split("::")[-1].split(".")[-1] if "::" in key else key.split(".")[-1]
            if simple not in name_to_qualified:
                name_to_qualified[simple] = []
            name_to_qualified[simple].append(key)

    simple_to_qualified_graph: dict[str, list[str]] = {}
    for key in forward_graph:
        simple = key.split("::")[-1].split(".")[-1] if "::" in key else key.split(".")[-1]
        if simple not in simple_to_qualified_graph:
            simple_to_qualified_graph[simple] = []
        simple_to_qualified_graph[simple].append(key)

    reachable: set[str] = set()
    worklist = [start_func]

    while worklist:
        current = worklist.pop()
        if current in reachable:
            continue
        reachable.add(current)

        current_simple = (
            current.split("::")[-1].split(".")[-1] if "::" in current else current.split(".")[-1]
        )
        reachable.add(current_simple)

        callees = forward_graph.get(current, set())
        if not callees:
            for qualified_key in simple_to_qualified_graph.get(current_simple, []):
                callees = forward_graph.get(qualified_key, set())
                if callees:
                    break

        for callee in callees:
            expanded = expand_polymorphic_call(
                callee,
                model.exception_hierarchy,
                name_to_qualified,
            )

            for impl in expanded:
                if impl not in reachable:
                    worklist.append(impl)
                impl_simple = (
                    impl.split("::")[-1].split(".")[-1] if "::" in impl else impl.split(".")[-1]
                )
                for qualified in name_to_qualified.get(impl_simple, []):
                    if qualified not in reachable:
                        worklist.append(qualified)

    return reachable


def compute_exception_flow(
    function_name: str,
    model: ProgramModel,
    propagation: PropagationResult,
    detected_frameworks: set[str] | None = None,
    get_framework_response: Callable[[str], str | None] | None = None,
) -> ExceptionFlow:
    """
    Compute the exception flow for a specific function.

    This is the core (framework-agnostic) version. For integration-aware
    exception flow, use flow.integrations.queries._compute_exception_flow_for_integration.

    Args:
        function_name: Name of the function to analyze
        model: The program model
        propagation: Propagation analysis results
        detected_frameworks: (Deprecated) Set of detected frameworks
        get_framework_response: Optional callback to check framework-handled exceptions

    Returns:
        ExceptionFlow with exceptions categorized as:
        - caught_by_global: Caught by global handlers
        - framework_handled: Converted to HTTP response (if get_framework_response provided)
        - uncaught: Will escape
    """
    _ = detected_frameworks

    flow = ExceptionFlow()

    func_key = None
    for key in propagation.propagated_raises:
        if key.endswith(f"::{function_name}") or key.endswith(f".{function_name}"):
            func_key = key
            break
        if "::" in key and key.split("::")[-1].split(".")[-1] == function_name:
            func_key = key
            break

    if func_key is None:
        return flow

    reachable = compute_reachable_functions(func_key, model, propagation)

    escaping_exceptions = propagation.propagated_raises.get(func_key, set())
    func_evidence = propagation.propagated_with_evidence.get(func_key, {})

    global_handler_types: dict[str, GlobalHandler] = {}
    for handler in model.global_handlers:
        global_handler_types[handler.handled_type] = handler
        global_handler_types[handler.handled_type.split(".")[-1]] = handler

    for exc_type in escaping_exceptions:
        exc_simple = exc_type.split(".")[-1]

        raise_sites = [
            r
            for r in model.raise_sites
            if (r.exception_type == exc_type or r.exception_type.split(".")[-1] == exc_simple)
            and (r.function in reachable or f"{r.file}::{r.function}" in reachable)
        ]

        evidence_list: list[ExceptionEvidence] = []
        for key, prop_raise in func_evidence.items():
            if key[0] == exc_type:
                evidence_list.append(
                    ExceptionEvidence(
                        raise_site=prop_raise.raise_site,
                        call_path=list(prop_raise.path),
                        confidence=compute_confidence(list(prop_raise.path)),
                    )
                )

        if evidence_list:
            if exc_type not in flow.evidence:
                flow.evidence[exc_type] = []
            flow.evidence[exc_type].extend(evidence_list)

        caught_by_handler = None
        for handler_type, handler in global_handler_types.items():
            handler_simple = handler_type.split(".")[-1]
            if exc_simple == handler_simple:
                caught_by_handler = handler
                break
            if model.exception_hierarchy.is_subclass_of(exc_simple, handler_simple):
                caught_by_handler = handler
                break

        if caught_by_handler:
            if exc_type not in flow.caught_by_global:
                flow.caught_by_global[exc_type] = []
            flow.caught_by_global[exc_type].extend(raise_sites)
            continue

        if get_framework_response:
            framework_response = get_framework_response(exc_type)
            if framework_response:
                if exc_type not in flow.framework_handled:
                    flow.framework_handled[exc_type] = []
                for rs in raise_sites:
                    flow.framework_handled[exc_type].append((rs, framework_response))
                continue

        if exc_type not in flow.uncaught:
            flow.uncaught[exc_type] = []
        flow.uncaught[exc_type].extend(raise_sites)

    return flow


def get_exceptions_for_entrypoint(
    entrypoint_function: str,
    model: ProgramModel,
) -> ExceptionFlow:
    """Get the exception flow for an entrypoint (deprecated, use integrations instead)."""
    propagation = propagate_exceptions(model)
    return compute_exception_flow(entrypoint_function, model, propagation)
