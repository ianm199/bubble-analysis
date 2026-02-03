"""Query functions for analyzing the program model.

Each function takes a ProgramModel and query parameters,
and returns a typed result dataclass. No formatting here.
"""

from difflib import get_close_matches

from bubble.enums import EntrypointKind, Framework, ResolutionMode
from bubble.models import CatchSite, ClassHierarchy, Entrypoint, ProgramModel, RaiseSite
from bubble.propagation import (
    build_forward_call_graph,
    build_reverse_call_graph,
    compute_exception_flow,
    compute_forward_reachability,
    propagate_exceptions,
)
from bubble.results import (
    AuditIssue,
    AuditResult,
    CallersResult,
    CatchesResult,
    EntrypointsResult,
    EntrypointsToResult,
    EntrypointTrace,
    EscapesResult,
    ExceptionClass,
    ExceptionsResult,
    InitResult,
    PolymorphicNode,
    RaisesResult,
    StatsResult,
    SubclassesResult,
    SubclassInfo,
    TraceNode,
    TraceResult,
)


def find_similar_names(target: str, candidates: list[str], n: int = 3) -> list[str]:
    """Find similar names using fuzzy matching."""
    return get_close_matches(target, candidates, n=n, cutoff=0.5)


def find_raises(
    model: ProgramModel,
    exception_type: str,
    include_subclasses: bool = False,
) -> RaisesResult:
    """Find all raise sites matching an exception type."""
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

    return RaisesResult(
        exception_type=exception_type,
        include_subclasses=include_subclasses,
        types_searched=types_to_find,
        matches=matching_raises,
    )


def find_exceptions(model: ProgramModel) -> ExceptionsResult:
    """List the exception hierarchy in the codebase."""
    exception_bases = {"Exception", "BaseException"}
    exception_classes: dict[str, ExceptionClass] = {}

    for cls in model.exception_hierarchy.classes.values():
        for base in cls.bases:
            base_simple = base.split(".")[-1]
            if (
                base_simple in exception_bases
                or base_simple in exception_classes
                or "Exception" in base
                or "Error" in base
            ):
                exception_classes[cls.name] = ExceptionClass(
                    name=cls.name,
                    bases=cls.bases,
                    file=cls.file,
                    line=cls.line,
                )
                exception_bases.add(cls.name)
                break

    roots: set[str] = set()
    for name, exc_class in exception_classes.items():
        base_names = [b.split(".")[-1] for b in exc_class.bases]
        has_parent_in_codebase = any(b in exception_classes for b in base_names)
        if not has_parent_in_codebase:
            roots.add(name)

    return ExceptionsResult(
        classes=exception_classes,
        roots=roots,
        hierarchy=model.exception_hierarchy,
    )


def get_stats(model: ProgramModel) -> StatsResult:
    """Get codebase statistics."""
    http_routes = [e for e in model.entrypoints if e.kind == EntrypointKind.HTTP_ROUTE]
    cli_scripts = [e for e in model.entrypoints if e.kind == EntrypointKind.CLI_SCRIPT]

    return StatsResult(
        functions=len(model.functions),
        classes=len(model.classes),
        raise_sites=len(model.raise_sites),
        catch_sites=len(model.catch_sites),
        call_sites=len(model.call_sites),
        entrypoints=len(model.entrypoints),
        http_routes=len(http_routes),
        cli_scripts=len(cli_scripts),
        global_handlers=len(model.global_handlers),
        imports=len(model.imports),
    )


def find_callers(model: ProgramModel, function_name: str) -> CallersResult:
    """Find all callers of a function."""
    calls = model.get_callers(function_name)

    suggestions: list[str] = []
    if not calls:
        all_functions = [f.name for f in model.functions.values()]
        all_entrypoints = [e.function for e in model.entrypoints]
        all_names = list(set(all_functions + all_entrypoints))
        suggestions = find_similar_names(function_name, all_names)

    return CallersResult(
        function_name=function_name,
        calls=calls,
        suggestions=suggestions,
    )


def get_callers_from_graphs(
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


def trace_to_entrypoints(
    function_name: str,
    qualified_graph: dict[str, set[str]],
    name_graph: dict[str, set[str]],
    entrypoint_functions: set[str],
    max_depth: int = 20,
) -> list[list[str]]:
    """Trace call paths from function to entrypoints."""
    paths: list[list[str]] = []

    def dfs(current: str, path: list[str], visited: set[str]) -> None:
        if len(path) > max_depth:
            return
        if current in visited:
            return
        visited.add(current)

        current_simple = current.split("::")[-1] if "::" in current else current
        current_simple = current_simple.split(".")[-1]

        if current in entrypoint_functions or current_simple in entrypoint_functions:
            paths.append(list(path))
            return

        callers = get_callers_from_graphs(current, qualified_graph, name_graph)
        for caller in callers:
            dfs(caller, path + [caller], visited.copy())

    dfs(function_name, [function_name], set())
    return paths


def trace_entrypoints_to(
    model: ProgramModel,
    exception_type: str,
    include_subclasses: bool = False,
) -> EntrypointsToResult:
    """Trace which entrypoints can reach an exception."""
    raises_result = find_raises(model, exception_type, include_subclasses)

    qualified_graph, name_graph = build_reverse_call_graph(model)
    entrypoint_functions = {e.function for e in model.entrypoints}

    traces: list[EntrypointTrace] = []
    for raise_site in raises_result.matches:
        paths = trace_to_entrypoints(
            raise_site.function,
            qualified_graph,
            name_graph,
            entrypoint_functions,
        )
        entrypoints_reached: set[str] = set()
        for path in paths:
            if path:
                endpoint = path[-1]
                entrypoints_reached.add(endpoint)
                if "::" in endpoint:
                    entrypoints_reached.add(endpoint.split("::")[-1].split(".")[-1])

        matching_entrypoints = [e for e in model.entrypoints if e.function in entrypoints_reached]

        traces.append(
            EntrypointTrace(
                raise_site=raise_site,
                paths=paths,
                entrypoints=matching_entrypoints,
            )
        )

    return EntrypointsToResult(
        exception_type=exception_type,
        include_subclasses=include_subclasses,
        types_searched=raises_result.types_searched,
        traces=traces,
    )


def list_entrypoints(model: ProgramModel) -> EntrypointsResult:
    """List all entrypoints in the codebase."""
    http_routes = [e for e in model.entrypoints if e.kind == EntrypointKind.HTTP_ROUTE]
    cli_scripts = [e for e in model.entrypoints if e.kind == EntrypointKind.CLI_SCRIPT]

    other: dict[str, list[Entrypoint]] = {}
    for e in model.entrypoints:
        if e.kind not in (EntrypointKind.HTTP_ROUTE, EntrypointKind.CLI_SCRIPT):
            kind = e.kind or EntrypointKind.UNKNOWN
            if kind not in other:
                other[kind] = []
            other[kind].append(e)

    return EntrypointsResult(
        http_routes=http_routes,
        cli_scripts=cli_scripts,
        other=other,
    )


def audit_entrypoints(model: ProgramModel) -> AuditResult:
    """Audit all entrypoints for escaping exceptions."""
    if not model.entrypoints:
        return AuditResult(total_entrypoints=0, issues=[], clean_count=0)

    propagation = propagate_exceptions(model)
    reraise_patterns = {"Unknown", "e", "ex", "err", "exc", "error", "exception"}

    issues: list[AuditIssue] = []
    clean_count = 0

    for entrypoint in model.entrypoints:
        flow = compute_exception_flow(entrypoint.function, model, propagation)

        if flow.uncaught:
            real_uncaught = {k: v for k, v in flow.uncaught.items() if k not in reraise_patterns}

            if real_uncaught:
                issues.append(
                    AuditIssue(
                        entrypoint=entrypoint,
                        uncaught=real_uncaught,
                        caught=flow.caught_by_global,
                    )
                )
            else:
                clean_count += 1
        else:
            clean_count += 1

    return AuditResult(
        total_entrypoints=len(model.entrypoints),
        issues=issues,
        clean_count=clean_count,
    )


def find_escapes(
    model: ProgramModel,
    function_name: str,
    resolution_mode: ResolutionMode = ResolutionMode.DEFAULT,
) -> EscapesResult:
    """Find exceptions that can escape from a function."""
    entrypoint = None
    for e in model.entrypoints:
        if e.function == function_name:
            entrypoint = e
            break

    forward_graph = build_forward_call_graph(model)
    scope = compute_forward_reachability(function_name, model, forward_graph)

    propagation = propagate_exceptions(
        model,
        resolution_mode=resolution_mode,
        skip_evidence=True,
        scope=scope,
    )
    flow = compute_exception_flow(function_name, model, propagation)

    return EscapesResult(
        function_name=function_name,
        entrypoint=entrypoint,
        flow=flow,
        global_handlers=list(model.global_handlers),
    )


def _compute_reverse_reachability(
    raise_sites: list[RaiseSite],
    qualified_graph: dict[str, set[str]],
    name_graph: dict[str, set[str]],
) -> set[str]:
    """Compute all functions that can transitively call the raise site functions."""
    reachable: set[str] = set()

    for raise_site in raise_sites:
        func_key = f"{raise_site.file}::{raise_site.function}"
        worklist = [func_key]
        visited: set[str] = set()

        while worklist:
            current = worklist.pop()
            if current in visited:
                continue
            visited.add(current)
            reachable.add(current)

            simple_name = (
                current.split("::")[-1].split(".")[-1]
                if "::" in current
                else current.split(".")[-1]
            )
            reachable.add(simple_name)

            for caller in qualified_graph.get(current, set()):
                if caller not in visited:
                    worklist.append(caller)

            for caller in name_graph.get(simple_name, set()):
                if caller not in visited:
                    worklist.append(caller)

    return reachable


def _catch_site_catches_exception(
    catch_site: CatchSite,
    types_to_find: set[str],
    hierarchy: ClassHierarchy,
) -> bool:
    """Check if a catch site would catch the given exception type."""
    if catch_site.has_bare_except:
        return True

    for caught_type in catch_site.caught_types:
        caught_simple = caught_type.split(".")[-1]

        if caught_type in types_to_find or caught_simple in types_to_find:
            return True

        if caught_simple in ("Exception", "BaseException"):
            return True

        for t in types_to_find:
            t_simple = t.split(".")[-1]
            if hierarchy.is_subclass_of(t_simple, caught_simple):
                return True

    return False


def find_catches(
    model: ProgramModel,
    exception_type: str,
    include_subclasses: bool = False,
) -> CatchesResult:
    """Find catch sites that are in the call path from where the exception is raised."""
    types_to_find: set[str] = {exception_type}
    if include_subclasses:
        subclasses = model.exception_hierarchy.get_subclasses(exception_type)
        types_to_find.update(subclasses)

    raises_result = find_raises(model, exception_type, include_subclasses)

    if not raises_result.matches:
        return CatchesResult(
            exception_type=exception_type,
            include_subclasses=include_subclasses,
            types_searched=types_to_find,
            local_catches=[],
            global_handlers=[],
            raise_site_count=0,
        )

    qualified_graph, name_graph = build_reverse_call_graph(model)
    reachable_functions = _compute_reverse_reachability(
        raises_result.matches, qualified_graph, name_graph
    )

    matching_catches: list[CatchSite] = []
    for catch_site in model.catch_sites:
        catch_func_key = f"{catch_site.file}::{catch_site.function}"
        catch_func_simple = catch_site.function.split(".")[-1]

        if catch_func_key not in reachable_functions and catch_func_simple not in reachable_functions:
            continue

        if _catch_site_catches_exception(
            catch_site, types_to_find, model.exception_hierarchy
        ):
            matching_catches.append(catch_site)

    global_handlers = [
        h
        for h in model.global_handlers
        if h.handled_type in types_to_find
        or h.handled_type.split(".")[-1] in types_to_find
        or any(
            model.exception_hierarchy.is_subclass_of(t, h.handled_type.split(".")[-1])
            for t in types_to_find
        )
    ]

    return CatchesResult(
        exception_type=exception_type,
        include_subclasses=include_subclasses,
        types_searched=types_to_find,
        local_catches=matching_catches,
        global_handlers=global_handlers,
        raise_site_count=len(raises_result.matches),
    )


def find_function_key(
    function_name: str,
    propagated_raises: dict[str, set[str]],
    model: ProgramModel,
) -> str | None:
    """Find the qualified key for a function name."""
    for key in propagated_raises:
        if key.endswith(f"::{function_name}") or key.endswith(f".{function_name}"):
            return key
        if "::" in key and key.split("::")[-1].split(".")[-1] == function_name:
            return key

    for call_site in model.call_sites:
        if call_site.caller_function == function_name:
            return call_site.caller_qualified or f"{call_site.file}::{call_site.caller_function}"

    return None


def get_direct_raises_for_key(
    func_key: str,
    direct_raises: dict[str, set[str]],
) -> set[str]:
    """Get direct raises for a function key."""
    if func_key in direct_raises:
        return direct_raises[func_key]

    simple_name = (
        func_key.split("::")[-1].split(".")[-1] if "::" in func_key else func_key.split(".")[-1]
    )
    for key, raises in direct_raises.items():
        key_simple = key.split("::")[-1].split(".")[-1] if "::" in key else key.split(".")[-1]
        if key_simple == simple_name:
            return raises

    return set()


def expand_callee(callee: str, model: ProgramModel) -> list[str]:
    """Expand a callee to concrete implementations if polymorphic."""
    if "." not in callee:
        return [callee]

    parts = callee.split("::")[-1].split(".") if "::" in callee else callee.split(".")
    if len(parts) < 2:
        return [callee]

    method_name = parts[-1]
    class_name = parts[-2]

    hierarchy = model.exception_hierarchy
    if not hierarchy.is_abstract_method(class_name, method_name):
        return [callee]

    implementations = hierarchy.get_concrete_implementations(class_name, method_name)
    if not implementations:
        return [callee]

    result: list[str] = []
    for impl_class, _ in implementations:
        for func in model.functions.values():
            if func.name == method_name and impl_class in func.qualified_name:
                result.append(func.qualified_name)
                break
        else:
            result.append(f"{impl_class}.{method_name}")

    return result if result else [callee]


def _build_trace_node(
    func_key: str,
    forward_graph: dict[str, set[str]],
    direct_raises: dict[str, set[str]],
    propagated_raises: dict[str, set[str]],
    model: ProgramModel,
    max_depth: int,
    show_all: bool,
    visited: set[str],
    current_depth: int = 0,
) -> TraceNode | None:
    """Build a trace tree node recursively."""
    if current_depth >= max_depth or func_key in visited:
        return None

    visited = visited | {func_key}

    simple_name = (
        func_key.split("::")[-1].split(".")[-1] if "::" in func_key else func_key.split(".")[-1]
    )
    this_direct = get_direct_raises_for_key(func_key, direct_raises)
    this_propagated = propagated_raises.get(func_key, set())

    callees = forward_graph.get(func_key, set())
    if not callees:
        for key in forward_graph:
            key_simple = key.split("::")[-1].split(".")[-1] if "::" in key else key.split(".")[-1]
            if key_simple == simple_name:
                callees = forward_graph[key]
                break

    children: list[TraceNode | PolymorphicNode] = []
    for callee in sorted(callees):
        implementations = expand_callee(callee, model)
        callee_propagated: set[str] = set()
        for impl in implementations:
            callee_propagated |= propagated_raises.get(impl, set())

        if not show_all and not callee_propagated:
            continue

        if len(implementations) > 1:
            impl_nodes: list[TraceNode] = []
            for impl in implementations:
                impl_node = _build_trace_node(
                    impl,
                    forward_graph,
                    direct_raises,
                    propagated_raises,
                    model,
                    max_depth,
                    show_all,
                    visited,
                    current_depth + 1,
                )
                if impl_node:
                    impl_nodes.append(impl_node)

            if impl_nodes:
                children.append(
                    PolymorphicNode(
                        function=callee,
                        implementations=impl_nodes,
                        raises=sorted(callee_propagated),
                    )
                )
        else:
            child_node = _build_trace_node(
                implementations[0] if implementations else callee,
                forward_graph,
                direct_raises,
                propagated_raises,
                model,
                max_depth,
                show_all,
                visited,
                current_depth + 1,
            )
            if child_node:
                children.append(child_node)

    return TraceNode(
        function=simple_name,
        qualified=func_key,
        direct_raises=sorted(this_direct),
        propagated_raises=sorted(this_propagated),
        calls=children,
    )


def trace_function(
    model: ProgramModel,
    function_name: str,
    max_depth: int = 10,
    show_all: bool = False,
) -> TraceResult:
    """Trace exception flow from a function."""
    entrypoint = None
    for e in model.entrypoints:
        if e.function == function_name:
            entrypoint = e
            break

    propagation = propagate_exceptions(model)
    forward_graph = build_forward_call_graph(model)
    direct_raises = propagation.direct_raises
    propagated_raises = propagation.propagated_raises

    func_key = find_function_key(function_name, propagated_raises, model)
    escaping = propagated_raises.get(func_key, set()) if func_key else set()

    root = None
    if func_key:
        root = _build_trace_node(
            func_key,
            forward_graph,
            direct_raises,
            propagated_raises,
            model,
            max_depth,
            show_all,
            set(),
        )

    return TraceResult(
        function_name=function_name,
        entrypoint=entrypoint,
        root=root,
        escaping_exceptions=escaping,
    )


def find_subclasses(model: ProgramModel, class_name: str) -> SubclassesResult:
    """Find all subclasses of a class."""
    hierarchy = model.exception_hierarchy

    base_class = hierarchy.classes.get(class_name)
    if not base_class:
        for name, cls in hierarchy.classes.items():
            if name.endswith(class_name) or cls.qualified_name.endswith(class_name):
                base_class = cls
                class_name = name
                break

    subclasses: list[SubclassInfo] = []
    if base_class:
        for name in sorted(hierarchy.get_all_subclasses(class_name)):
            cls = hierarchy.classes.get(name)
            subclasses.append(
                SubclassInfo(
                    name=name,
                    file=cls.file if cls else None,
                    line=cls.line if cls else None,
                    is_abstract=cls.is_abstract if cls else False,
                )
            )

    return SubclassesResult(
        class_name=class_name,
        base_class_file=base_class.file if base_class else None,
        base_class_line=base_class.line if base_class else None,
        is_abstract=base_class.is_abstract if base_class else False,
        abstract_methods=base_class.abstract_methods if base_class else set(),
        subclasses=subclasses,
    )


def get_init_info(model: ProgramModel, directory_name: str) -> InitResult:
    """Get info needed for init command."""
    http_routes = [e for e in model.entrypoints if e.kind == EntrypointKind.HTTP_ROUTE]
    cli_scripts = [e for e in model.entrypoints if e.kind == EntrypointKind.CLI_SCRIPT]

    frameworks: list[str] = []
    flask_routes = [e for e in http_routes if e.metadata.get("framework") == Framework.FLASK]
    fastapi_routes = [e for e in http_routes if e.metadata.get("framework") == Framework.FASTAPI]

    if flask_routes:
        frameworks.append("Flask")
    if fastapi_routes:
        frameworks.append("FastAPI")
    if cli_scripts:
        frameworks.append("CLI scripts")

    return InitResult(
        flow_dir=f"{directory_name}/.flow",
        functions_count=len(model.functions),
        http_routes_count=len(http_routes),
        cli_scripts_count=len(cli_scripts),
        exception_classes_count=len(model.exception_hierarchy.classes),
        global_handlers_count=len(model.global_handlers),
        frameworks_detected=frameworks,
    )
