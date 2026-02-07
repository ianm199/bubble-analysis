"""Query functions for integration-specific operations.

Shared audit/entrypoint logic that all integrations use.
"""

from typing import TYPE_CHECKING

from bubble.config import FlowConfig
from bubble.integrations.base import Entrypoint, GlobalHandler, Integration
from bubble.integrations.models import (
    AuditIssue,
    AuditResult,
    EntrypointsResult,
    EntrypointTrace,
    RoutesToResult,
)
from bubble.models import ProgramModel, RaiseSite
from bubble.propagation import (
    ExceptionFlow,
    PropagationResult,
    build_forward_call_graph,
    build_name_to_qualified,
    build_reverse_call_graph,
    compute_reachable_functions,
    propagate_exceptions,
)

if TYPE_CHECKING:
    from bubble.stubs import StubLibrary


def _filter_async_boundaries(
    forward_graph: dict[str, set[str]], config: FlowConfig
) -> dict[str, set[str]]:
    """Remove calls that match async boundary patterns from the call graph.

    Async boundaries (like Celery's .apply_async() or .delay()) spawn background
    tasks where exceptions don't propagate back to the caller.
    """
    filtered: dict[str, set[str]] = {}
    for caller, callees in forward_graph.items():
        filtered_callees = {callee for callee in callees if not config.is_async_boundary(callee)}
        if filtered_callees:
            filtered[caller] = filtered_callees
    return filtered


def _compute_exception_flow_for_integration(
    function_name: str,
    model: ProgramModel,
    propagation: PropagationResult,
    integration: Integration,
    global_handlers: list[GlobalHandler],
    forward_graph: dict[str, set[str]] | None = None,
    name_to_qualified: dict[str, list[str]] | None = None,
    config: FlowConfig | None = None,
    entrypoint_file: str | None = None,
) -> ExceptionFlow:
    """Compute exception flow for a function with integration-specific handling.

    Categorizes exceptions as:
    - caught_locally: By try/except in the function
    - caught_by_global: By global handler
    - framework_handled: Converted to HTTP response (or handled by handled_base_classes)
    - uncaught: Will escape

    For better performance when calling repeatedly, pre-compute forward_graph and
    name_to_qualified using build_forward_call_graph() and build_name_to_qualified().
    """
    from bubble.models import ExceptionEvidence, compute_confidence

    flow = ExceptionFlow()
    handled_base_classes = config.handled_base_classes if config else []

    if function_name in propagation.propagated_raises:
        func_key = function_name
    else:
        func_key = None
        for key in propagation.propagated_raises:
            if "::" in key and key.split("::")[-1] == function_name:
                func_key = key
                break
            if "::" in key and key.split("::")[-1].split(".")[-1] == function_name:
                func_key = key
                break

    if func_key is None:
        return flow

    reachable = compute_reachable_functions(
        func_key, model, propagation, forward_graph, name_to_qualified
    )

    escaping_exceptions = propagation.propagated_raises.get(func_key, set())
    func_evidence = propagation.propagated_with_evidence.get(func_key, {})

    global_handler_types: dict[str, GlobalHandler] = {}
    for handler in global_handlers:
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
            if caught_by_handler.is_generic:
                if exc_type not in flow.caught_by_generic:
                    flow.caught_by_generic[exc_type] = []
                flow.caught_by_generic[exc_type].extend(raise_sites)
            else:
                is_same_file = (
                    entrypoint_file is not None and caught_by_handler.file == entrypoint_file
                )
                if is_same_file:
                    if exc_type not in flow.caught_by_global:
                        flow.caught_by_global[exc_type] = []
                    flow.caught_by_global[exc_type].extend(raise_sites)
                else:
                    if exc_type not in flow.caught_by_remote_global:
                        flow.caught_by_remote_global[exc_type] = []
                    flow.caught_by_remote_global[exc_type].extend(raise_sites)
            continue

        framework_response = integration.get_exception_response(exc_type)
        if framework_response:
            if exc_type not in flow.framework_handled:
                flow.framework_handled[exc_type] = []
            for rs in raise_sites:
                flow.framework_handled[exc_type].append((rs, framework_response))
            continue

        is_handled_by_config = False
        for base_class in handled_base_classes:
            base_simple = base_class.split(".")[-1]
            if exc_simple == base_simple or exc_type == base_class:
                is_handled_by_config = True
                break
            if model.exception_hierarchy.is_subclass_of(exc_simple, base_simple):
                is_handled_by_config = True
                break
            if model.exception_hierarchy.is_subclass_of(exc_type, base_class):
                is_handled_by_config = True
                break

        if is_handled_by_config:
            if exc_type not in flow.framework_handled:
                flow.framework_handled[exc_type] = []
            for rs in raise_sites:
                flow.framework_handled[exc_type].append((rs, "handled by config"))
            continue

        if exc_type not in flow.uncaught:
            flow.uncaught[exc_type] = []
        flow.uncaught[exc_type].extend(raise_sites)

    return flow


def audit_integration(
    model: ProgramModel,
    integration: Integration,
    entrypoints: list[Entrypoint],
    global_handlers: list[GlobalHandler],
    skip_evidence: bool = True,
    config: FlowConfig | None = None,
    stub_library: "StubLibrary | None" = None,
) -> AuditResult:
    """Audit entrypoints for a specific integration.

    Args:
        skip_evidence: Skip building evidence paths for faster auditing.
                       Set to False if you need path details.
        config: Optional FlowConfig with handled_base_classes and async_boundaries.
        stub_library: Optional stub library for external library exceptions.
    """
    if not entrypoints:
        return AuditResult(
            integration_name=integration.name,
            total_entrypoints=0,
            issues=[],
            clean_count=0,
        )

    propagation = propagate_exceptions(
        model, skip_evidence=skip_evidence, stub_library=stub_library
    )
    reraise_patterns = {"Unknown", "e", "ex", "err", "exc", "error", "exception"}

    forward_graph = build_forward_call_graph(model)
    if config and config.async_boundaries:
        forward_graph = _filter_async_boundaries(forward_graph, config)
    name_to_qualified = build_name_to_qualified(propagation)

    issues: list[AuditIssue] = []
    clean_count = 0

    for entrypoint in entrypoints:
        flow = _compute_exception_flow_for_integration(
            entrypoint.function,
            model,
            propagation,
            integration,
            global_handlers,
            forward_graph,
            name_to_qualified,
            config,
            entrypoint_file=entrypoint.file,
        )

        real_uncaught = {k: v for k, v in flow.uncaught.items() if k not in reraise_patterns}
        real_generic = {
            k: v for k, v in flow.caught_by_generic.items() if k not in reraise_patterns
        }
        real_remote = {
            k: v for k, v in flow.caught_by_remote_global.items() if k not in reraise_patterns
        }

        if real_uncaught or real_generic:
            issues.append(
                AuditIssue(
                    entrypoint=entrypoint,
                    uncaught=real_uncaught,
                    caught_by_generic=real_generic,
                    caught_by_remote=real_remote,
                    caught=flow.caught_by_global,
                )
            )
        else:
            clean_count += 1

    return AuditResult(
        integration_name=integration.name,
        total_entrypoints=len(entrypoints),
        issues=issues,
        clean_count=clean_count,
    )


def list_integration_entrypoints(
    integration: Integration,
    entrypoints: list[Entrypoint],
) -> EntrypointsResult:
    """List entrypoints for a specific integration."""
    return EntrypointsResult(
        integration_name=integration.name,
        entrypoints=entrypoints,
    )


def _find_raises(
    model: ProgramModel,
    exception_type: str,
    include_subclasses: bool,
) -> tuple[set[str], list[RaiseSite]]:
    """Find raise sites matching an exception type. Returns (types_searched, matches)."""
    types_to_find: set[str] = {exception_type}
    if include_subclasses:
        subclasses = model.exception_hierarchy.get_subclasses(exception_type)
        types_to_find.update(subclasses)

    matching_raises = [
        r
        for r in model.raise_sites
        if r.exception_type in types_to_find
        or r.exception_type.endswith(f".{exception_type}")
        or any(r.exception_type.endswith(f".{t}") for t in types_to_find)
    ]

    for t in list(types_to_find):
        for r in model.raise_sites:
            simple_name = r.exception_type.split(".")[-1]
            if simple_name == t and r not in matching_raises:
                matching_raises.append(r)

    return types_to_find, matching_raises


def _get_callers_from_graphs(
    function_name: str,
    qualified_graph: dict[str, set[str]],
    name_graph: dict[str, set[str]],
) -> set[str]:
    """Get callers using qualified graph first, falling back to name graph."""
    callers = qualified_graph.get(function_name, set())
    if not callers:
        simple_name = (
            function_name.split("::")[-1].split(".")[-1] if "::" in function_name else function_name
        )
        callers = name_graph.get(simple_name, set())
    return callers


def _compute_entrypoint_reachability(
    qualified_graph: dict[str, set[str]],
    name_graph: dict[str, set[str]],
    entrypoint_functions: set[str],
) -> tuple[set[str], dict[str, str]]:
    """
    Compute which functions are reachable from entrypoints via forward BFS.

    A function is reachable if an entrypoint calls it (directly or transitively).
    This is used to prune the search space when tracing from raise sites back
    to entrypoints - we only explore functions that could possibly connect.

    Returns (reachable_set, function_to_entrypoint_map).
    """
    reachable: set[str] = set()
    func_to_entrypoint: dict[str, str] = {}

    for ep in entrypoint_functions:
        reachable.add(ep)
        func_to_entrypoint[ep] = ep

    forward_graph: dict[str, set[str]] = {}
    for callee, callers in qualified_graph.items():
        for caller in callers:
            if caller not in forward_graph:
                forward_graph[caller] = set()
            forward_graph[caller].add(callee)
    for callee, callers in name_graph.items():
        for caller in callers:
            if caller not in forward_graph:
                forward_graph[caller] = set()
            forward_graph[caller].add(callee)

    simple_to_qualified: dict[str, list[str]] = {}
    for key in forward_graph:
        simple = key.split("::")[-1].split(".")[-1] if "::" in key else key.split(".")[-1]
        if simple not in simple_to_qualified:
            simple_to_qualified[simple] = []
        simple_to_qualified[simple].append(key)

    worklist = list(entrypoint_functions)
    iterations = 0
    max_iterations = 10000

    while worklist and iterations < max_iterations:
        iterations += 1
        func = worklist.pop()

        func_simple = func.split("::")[-1].split(".")[-1] if "::" in func else func.split(".")[-1]

        callees: set[str] = set()
        callees.update(forward_graph.get(func, set()))
        for qualified_key in simple_to_qualified.get(func_simple, []):
            callees.update(forward_graph.get(qualified_key, set()))

        for callee in callees:
            callee_simple = (
                callee.split("::")[-1].split(".")[-1] if "::" in callee else callee.split(".")[-1]
            )

            if callee not in reachable:
                reachable.add(callee)
                reachable.add(callee_simple)
                if func in func_to_entrypoint:
                    func_to_entrypoint[callee] = func_to_entrypoint[func]
                worklist.append(callee)

            if callee_simple not in reachable:
                reachable.add(callee_simple)
                worklist.append(callee_simple)

    return reachable, func_to_entrypoint


def _trace_to_entrypoints(
    function_name: str,
    qualified_graph: dict[str, set[str]],
    name_graph: dict[str, set[str]],
    entrypoint_functions: set[str],
    reachable_from_entrypoints: set[str] | None = None,
    max_depth: int = 20,
    max_paths: int = 150,
) -> list[list[str]]:
    """
    Trace call paths from function to entrypoints.

    Uses reachability pruning: only explores branches that can reach entrypoints.
    Limits to max_paths to avoid exponential blowup.
    """
    paths: list[list[str]] = []

    def dfs(current: str, path: list[str], visited: set[str]) -> None:
        if len(paths) >= max_paths:
            return
        if len(path) > max_depth:
            return
        if current in visited:
            return
        visited.add(current)

        current_qualified = current.split("::")[-1] if "::" in current else current
        current_simple = current_qualified.split(".")[-1]

        if (
            current in entrypoint_functions
            or current_qualified in entrypoint_functions
            or current_simple in entrypoint_functions
        ):
            paths.append(list(path))
            return

        callers = _get_callers_from_graphs(current, qualified_graph, name_graph)
        for caller in callers:
            if len(paths) >= max_paths:
                return
            if reachable_from_entrypoints is not None:
                caller_qualified = caller.split("::")[-1] if "::" in caller else caller
                caller_simple = caller_qualified.split(".")[-1]
                if (
                    caller not in reachable_from_entrypoints
                    and caller_qualified not in reachable_from_entrypoints
                    and caller_simple not in reachable_from_entrypoints
                ):
                    continue
            dfs(caller, path + [caller], visited.copy())

    dfs(function_name, [function_name], set())
    return paths


def trace_routes_to_exception(
    model: ProgramModel,
    integration: Integration,
    entrypoints: list[Entrypoint],
    exception_type: str,
    include_subclasses: bool = False,
) -> RoutesToResult:
    """Trace which routes can reach an exception for a specific integration."""
    types_searched, raise_sites = _find_raises(model, exception_type, include_subclasses)

    qualified_graph, name_graph = build_reverse_call_graph(model)
    entrypoint_functions = {e.function for e in entrypoints}

    reachable, _ = _compute_entrypoint_reachability(
        qualified_graph, name_graph, entrypoint_functions
    )

    traces: list[EntrypointTrace] = []
    for raise_site in raise_sites:
        qualified_function = f"{raise_site.file}::{raise_site.function}"
        paths = _trace_to_entrypoints(
            qualified_function,
            qualified_graph,
            name_graph,
            entrypoint_functions,
            reachable_from_entrypoints=reachable,
        )
        entrypoints_reached: set[str] = set()
        for path in paths:
            if path:
                endpoint = path[-1]
                entrypoints_reached.add(endpoint)
                if "::" in endpoint:
                    qualified_part = endpoint.split("::")[-1]
                    entrypoints_reached.add(qualified_part)
                    entrypoints_reached.add(qualified_part.split(".")[-1])

        matching_entrypoints = [e for e in entrypoints if e.function in entrypoints_reached]

        traces.append(
            EntrypointTrace(
                raise_site=raise_site,
                paths=paths,
                entrypoints=matching_entrypoints,
            )
        )

    return RoutesToResult(
        integration_name=integration.name,
        exception_type=exception_type,
        include_subclasses=include_subclasses,
        types_searched=types_searched,
        traces=traces,
    )
