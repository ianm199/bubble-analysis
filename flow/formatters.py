"""Output formatters for CLI results.

Each formatter takes a result dataclass and renders it as text or JSON.
All Rich console output is contained here.
"""

import json
from pathlib import Path

from rich.console import Console
from rich.tree import Tree

from flow.results import (
    AuditResult,
    CallersResult,
    CatchesResult,
    EntrypointsResult,
    EntrypointsToResult,
    EscapesResult,
    ExceptionsResult,
    InitResult,
    PolymorphicNode,
    RaisesResult,
    StatsResult,
    SubclassesResult,
    TraceNode,
    TraceResult,
)


def _rel_path(file: str, directory: Path) -> str:
    """Get relative path for display."""
    if file.startswith(str(directory)):
        return str(Path(file).relative_to(directory))
    return file


def raises(
    result: RaisesResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format raises query result."""
    if output_format == "json":
        data = {
            "query": "raises",
            "exception": result.exception_type,
            "include_subclasses": result.include_subclasses,
            "types_searched": sorted(result.types_searched),
            "results": [
                {
                    "file": r.file,
                    "line": r.line,
                    "function": r.function,
                    "exception_type": r.exception_type,
                    "message": r.message_expr,
                    "code": r.code,
                }
                for r in result.matches
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if not result.matches:
        console.print(f"[yellow]No raise statements found for {result.exception_type}[/yellow]")
        return

    subclass_note = " (and subclasses)" if result.include_subclasses else ""
    console.print(
        f"\n[bold]{result.exception_type}{subclass_note}[/bold] raised in {len(result.matches)} locations:\n"
    )

    for r in sorted(result.matches, key=lambda x: (x.file, x.line)):
        rel = _rel_path(r.file, directory)
        console.print(f"  [cyan]{rel}:{r.line}[/cyan]  in [green]{r.function}()[/green]")
        if r.code:
            console.print(f"    [dim]{r.code}[/dim]")
        if result.include_subclasses and r.exception_type != result.exception_type:
            console.print(f"    [yellow][{r.exception_type} is a subclass][/yellow]")
        console.print()


def audit(
    result: AuditResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format audit query result."""
    if output_format == "json":
        data = {
            "query": "audit",
            "total_entrypoints": result.total_entrypoints,
            "with_issues": len(result.issues),
            "clean": result.clean_count,
            "issues": [
                {
                    "function": issue.entrypoint.function,
                    "kind": issue.entrypoint.kind,
                    "http_method": issue.entrypoint.metadata.get("http_method"),
                    "http_path": issue.entrypoint.metadata.get("http_path"),
                    "uncaught": {
                        exc_type: [{"file": r.file, "line": r.line, "function": r.function} for r in raises_list]
                        for exc_type, raises_list in issue.uncaught.items()
                    },
                }
                for issue in result.issues
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if result.total_entrypoints == 0:
        console.print("[yellow]No entrypoints found (HTTP routes or CLI scripts)[/yellow]")
        console.print("[dim]Run 'flow init' to set up custom detectors if needed.[/dim]")
        return

    console.print(f"\n[bold]Scanning {result.total_entrypoints} entrypoints...[/bold]\n")

    if result.issues:
        console.print(f"[red bold]✗ {len(result.issues)} entrypoints have uncaught exceptions:[/red bold]\n")

        for issue in result.issues:
            ep = issue.entrypoint
            if ep.kind == "http_route":
                method = ep.metadata.get("http_method", "?")
                path = ep.metadata.get("http_path", "?")
                label = f"[green]{method}[/green] [cyan]{path}[/cyan]"
            else:
                rel = _rel_path(ep.file, directory)
                label = f"[magenta]{rel}[/magenta]:[bold]{ep.function}[/bold]"

            console.print(f"  {label}")
            for exc_type, raise_sites in issue.uncaught.items():
                exc_simple = exc_type.split(".")[-1]
                for rs in raise_sites[:2]:
                    rel = _rel_path(rs.file, directory)
                    console.print(f"    └─ [red]{exc_simple}[/red] [dim]({rel}:{rs.line})[/dim]")
                if len(raise_sites) > 2:
                    console.print(f"    └─ [dim]...and {len(raise_sites) - 2} more[/dim]")
            console.print()
    else:
        console.print("[green bold]✓ All entrypoints have exception handlers[/green bold]\n")

    if result.clean_count > 0:
        console.print(f"[green]✓ {result.clean_count} entrypoints fully covered by exception handlers[/green]\n")

    if result.issues:
        console.print("[dim]Run 'flow escapes <function>' for details on a specific route.[/dim]")


def exceptions(
    result: ExceptionsResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format exceptions query result."""
    if output_format == "json":
        data = {
            "query": "exceptions",
            "classes": {
                name: {
                    "bases": exc.bases,
                    "location": f"{exc.file}:{exc.line}" if exc.file else None,
                }
                for name, exc in result.classes.items()
            },
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if not result.classes:
        console.print("[yellow]No exception classes found[/yellow]")
        return

    console.print("\n[bold]Exception hierarchy:[/bold]\n")

    def build_tree(parent_name: str, tree: Tree) -> None:
        children = [
            name
            for name, exc in result.classes.items()
            if any(b.split(".")[-1] == parent_name for b in exc.bases)
        ]
        for child in sorted(children):
            exc = result.classes[child]
            if exc.file:
                rel = _rel_path(exc.file, directory)
                label = f"{child} ([dim]{rel}:{exc.line}[/dim])"
            else:
                label = child
            subtree = tree.add(label)
            build_tree(child, subtree)

    for root in sorted(result.roots):
        exc = result.classes.get(root)
        if exc and exc.file:
            rel = _rel_path(exc.file, directory)
            label = f"[bold]{root}[/bold] ([dim]{rel}:{exc.line}[/dim])"
        else:
            label = f"[bold]{root}[/bold]"
        tree = Tree(label)
        build_tree(root, tree)
        console.print(tree)
        console.print()


def stats(
    result: StatsResult,
    output_format: str,
    console: Console,
) -> None:
    """Format stats query result."""
    if output_format == "json":
        data = {
            "query": "stats",
            "results": {
                "functions": result.functions,
                "classes": result.classes,
                "raise_sites": result.raise_sites,
                "catch_sites": result.catch_sites,
                "call_sites": result.call_sites,
                "entrypoints": result.entrypoints,
                "http_routes": result.http_routes,
                "cli_scripts": result.cli_scripts,
                "global_handlers": result.global_handlers,
                "imports": result.imports,
            },
        }
        console.print_json(json.dumps(data, indent=2))
        return

    console.print("\n[bold]Codebase Statistics:[/bold]\n")
    console.print(f"  Functions:          {result.functions:,}")
    console.print(f"  Classes:            {result.classes:,}")
    console.print(f"  Raise sites:        {result.raise_sites:,}")
    console.print(f"  Catch sites:        {result.catch_sites:,}")
    console.print(f"  Call sites:         {result.call_sites:,}")
    console.print(
        f"  Entrypoints:        {result.entrypoints:,} ({result.http_routes} HTTP, {result.cli_scripts} CLI)"
    )
    console.print(f"  Global handlers:    {result.global_handlers:,}")
    console.print(f"  Imports:            {result.imports:,}")
    console.print()


def callers(
    result: CallersResult,
    output_format: str,
    directory: Path,
    console: Console,
    show_resolution: bool = False,
) -> None:
    """Format callers query result."""
    if output_format == "json":
        data = {
            "query": "callers",
            "function": result.function_name,
            "count": len(result.calls),
            "results": [
                {
                    "file": c.file,
                    "line": c.line,
                    "caller_function": c.caller_function,
                    "caller_qualified": c.caller_qualified,
                    "callee_qualified": c.callee_qualified,
                    "resolution_kind": c.resolution_kind,
                    "is_method_call": c.is_method_call,
                }
                for c in result.calls
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if not result.calls:
        console.print(f"[yellow]No calls found to {result.function_name}[/yellow]")
        if result.suggestions:
            console.print("[yellow]Did you mean:[/yellow]")
            for s in result.suggestions:
                console.print(f"  [dim]- {s}[/dim]")
            console.print()
        return

    console.print(
        f"\n[bold]{result.function_name}[/bold] called in {len(result.calls)} locations:\n"
    )

    for c in sorted(result.calls, key=lambda x: (x.file, x.line)):
        rel = _rel_path(c.file, directory)
        call_type = "method" if c.is_method_call else "function"
        resolution = (
            f" [dim]\\[{c.resolution_kind}][/dim]"
            if show_resolution and c.resolution_kind != "unresolved"
            else ""
        )
        console.print(
            f"  [cyan]{rel}:{c.line}[/cyan]  in [green]{c.caller_function}()[/green] ({call_type} call){resolution}"
        )

    console.print()


def entrypoints_to(
    result: EntrypointsToResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format entrypoints-to query result."""
    if output_format == "json":
        json_traces = []
        for trace in result.traces:
            json_traces.append(
                {
                    "raise_site": {
                        "file": trace.raise_site.file,
                        "line": trace.raise_site.line,
                        "function": trace.raise_site.function,
                        "exception_type": trace.raise_site.exception_type,
                    },
                    "paths": trace.paths,
                    "entrypoints": [
                        {
                            "function": e.function,
                            "http_method": e.metadata.get("http_method"),
                            "http_path": e.metadata.get("http_path"),
                        }
                        for e in trace.entrypoints
                    ],
                }
            )
        data = {
            "query": "entrypoints-to",
            "exception": result.exception_type,
            "include_subclasses": result.include_subclasses,
            "results": json_traces,
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if not result.traces:
        console.print(f"[yellow]No raise statements found for {result.exception_type}[/yellow]")
        return

    subclass_note = " (and subclasses)" if result.include_subclasses else ""
    console.print(
        f"\n[bold]Entrypoints that can reach {result.exception_type}{subclass_note}:[/bold]\n"
    )

    for trace in result.traces:
        rel = _rel_path(trace.raise_site.file, directory)

        if not trace.entrypoints:
            console.print(
                f"  [cyan]{rel}:{trace.raise_site.line}[/cyan] in [green]{trace.raise_site.function}()[/green]"
            )
            console.print("    [dim]No HTTP entrypoints found in call chain[/dim]\n")
            continue

        console.print(
            f"  [cyan]{rel}:{trace.raise_site.line}[/cyan] in [green]{trace.raise_site.function}()[/green]"
        )
        for e in trace.entrypoints:
            method = e.metadata.get("http_method", "?")
            path = e.metadata.get("http_path", "?")
            console.print(f"    → [green]{method}[/green] [cyan]{path}[/cyan] ({e.function})")
        console.print()


def entrypoints(
    result: EntrypointsResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format entrypoints query result."""
    total = len(result.http_routes) + len(result.cli_scripts) + sum(
        len(v) for v in result.other.values()
    )

    if output_format == "json":
        data = {
            "query": "entrypoints",
            "count": total,
            "http_routes": len(result.http_routes),
            "cli_scripts": len(result.cli_scripts),
            "results": [
                {
                    "file": e.file,
                    "function": e.function,
                    "line": e.line,
                    "kind": e.kind,
                    "http_method": e.metadata.get("http_method"),
                    "http_path": e.metadata.get("http_path"),
                    "framework": e.metadata.get("framework"),
                }
                for e in result.http_routes + result.cli_scripts
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if total == 0:
        console.print("[yellow]No entrypoints found[/yellow]")
        console.print()
        console.print("[dim]Detected entrypoint types:[/dim]")
        console.print("[dim]  - HTTP routes: Flask @route, FastAPI @router.get/post/etc[/dim]")
        console.print("[dim]  - CLI scripts: if __name__ == '__main__'[/dim]")
        console.print()
        return

    if result.http_routes:
        console.print(f"\n[bold]HTTP Routes ({len(result.http_routes)} total):[/bold]\n")
        sorted_routes = sorted(
            result.http_routes,
            key=lambda e: (e.metadata.get("http_path", ""), e.metadata.get("http_method", "")),
        )
        for e in sorted_routes:
            method = e.metadata.get("http_method", "?")
            path = e.metadata.get("http_path", "?")
            rel = _rel_path(e.file, directory)
            console.print(
                f"  [green]{method:6}[/green] [cyan]{path:40}[/cyan] {rel}:[bold]{e.function}[/bold]"
            )
        console.print()

    if result.cli_scripts:
        console.print(f"\n[bold]CLI Scripts ({len(result.cli_scripts)} total):[/bold]\n")
        sorted_scripts = sorted(result.cli_scripts, key=lambda e: e.file)
        for e in sorted_scripts:
            rel = _rel_path(e.file, directory)
            if e.metadata.get("inline"):
                console.print(f"  [magenta]{rel}[/magenta]:[bold]{e.line}[/bold] [dim](inline code)[/dim]")
            else:
                console.print(f"  [magenta]{rel}[/magenta]:[bold]{e.function}[/bold]()")
        console.print()

    for kind, entries in sorted(result.other.items()):
        kind_label = kind.replace("_", " ").title()
        console.print(f"\n[bold]{kind_label} ({len(entries)} total):[/bold]\n")
        for e in sorted(entries, key=lambda x: x.file):
            rel = _rel_path(e.file, directory)
            framework = e.metadata.get("framework", "")
            framework_note = f" [dim]({framework})[/dim]" if framework else ""
            console.print(f"  [yellow]{rel}[/yellow]:[bold]{e.function}[/bold](){framework_note}")
        console.print()


def _format_confidence(confidence: str) -> str:
    """Format confidence level with color."""
    if confidence == "high":
        return "[green]high[/green]"
    elif confidence == "medium":
        return "[yellow]medium[/yellow]"
    else:
        return "[red]low[/red]"


def _format_resolution_kind(kind: str) -> str:
    """Format resolution kind with optional warning."""
    heuristic_kinds = {"name_fallback", "polymorphic"}
    if kind in heuristic_kinds:
        return f"[yellow]{kind}[/yellow]"
    return f"[dim]{kind}[/dim]"


def escapes(
    result: EscapesResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format escapes query result."""
    if output_format == "json":
        entrypoint_info = None
        if result.entrypoint:
            entrypoint_info = {
                "kind": result.entrypoint.kind,
                "file": result.entrypoint.file,
                "line": result.entrypoint.line,
            }
            if result.entrypoint.kind == "http_route":
                entrypoint_info["http_method"] = result.entrypoint.metadata.get("http_method")
                entrypoint_info["http_path"] = result.entrypoint.metadata.get("http_path")

        evidence_json: dict[str, list[dict]] = {}
        for exc_type, evidence_list in result.flow.evidence.items():
            evidence_json[exc_type] = [
                {
                    "raise_site": {
                        "file": ev.raise_site.file,
                        "line": ev.raise_site.line,
                        "function": ev.raise_site.function,
                    },
                    "confidence": ev.confidence,
                    "call_path": [
                        {
                            "caller": edge.caller,
                            "callee": edge.callee,
                            "resolution": edge.resolution_kind,
                            "heuristic": edge.is_heuristic,
                        }
                        for edge in ev.call_path
                    ],
                }
                for ev in evidence_list
            ]

        framework_handled_json: dict[str, list[dict]] = {}
        for exc_type, handled_list in result.flow.framework_handled.items():
            framework_handled_json[exc_type] = [
                {
                    "raise_site": {"file": rs.file, "line": rs.line, "function": rs.function},
                    "http_response": response,
                }
                for rs, response in handled_list
            ]

        data = {
            "query": "escapes",
            "function": result.function_name,
            "entrypoint": entrypoint_info,
            "global_handlers": [
                {"type": h.handled_type, "function": h.function, "file": h.file}
                for h in result.global_handlers
            ],
            "caught_by_global": {
                exc_type: [
                    {"file": r.file, "line": r.line, "function": r.function} for r in raises
                ]
                for exc_type, raises in result.flow.caught_by_global.items()
            },
            "framework_handled": framework_handled_json,
            "uncaught": {
                exc_type: [
                    {"file": r.file, "line": r.line, "function": r.function} for r in raises
                ]
                for exc_type, raises in result.flow.uncaught.items()
            },
            "evidence": evidence_json,
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if result.entrypoint and result.entrypoint.kind == "http_route":
        method = result.entrypoint.metadata.get("http_method", "?")
        path = result.entrypoint.metadata.get("http_path", "?")
        console.print(f"\n[bold]Exceptions that can escape from {method} {path}:[/bold]\n")
    elif result.entrypoint and result.entrypoint.kind == "cli_script":
        rel = _rel_path(result.entrypoint.file, directory)
        console.print(
            f"\n[bold]Exceptions that can escape from CLI script {rel}:{result.function_name}():[/bold]\n"
        )
    else:
        console.print(f"\n[bold]Exceptions that can escape from {result.function_name}():[/bold]\n")

    has_content = (
        result.flow.caught_by_global
        or result.flow.uncaught
        or result.flow.framework_handled
    )
    if not has_content:
        console.print("  [dim]No escaping exceptions detected[/dim]\n")
        return

    if result.flow.caught_by_global:
        console.print("  [green]CAUGHT BY GLOBAL HANDLER:[/green]")
        for exc_type, raise_sites in result.flow.caught_by_global.items():
            exc_simple = exc_type.split(".")[-1]
            handler = next(
                (
                    h
                    for h in result.global_handlers
                    if h.handled_type == exc_type
                    or h.handled_type.split(".")[-1] == exc_simple
                ),
                None,
            )
            handler_info = f" (@errorhandler({handler.handled_type}))" if handler else ""
            console.print(f"    [cyan]{exc_type}[/cyan]{handler_info}")
            for r in raise_sites[:3]:
                rel = _rel_path(r.file, directory)
                console.print(f"      └─ raised in: [dim]{rel}:{r.line}[/dim] ({r.function})")
            if len(raise_sites) > 3:
                console.print(f"      └─ [dim]...and {len(raise_sites) - 3} more[/dim]")
        console.print()

    if result.flow.framework_handled:
        console.print("  [blue]FRAMEWORK-HANDLED (converted to HTTP response):[/blue]")
        for exc_type, handled_list in result.flow.framework_handled.items():
            exc_simple = exc_type.split(".")[-1]
            response = handled_list[0][1] if handled_list else "HTTP ?"
            console.print(f"    [cyan]{exc_simple}[/cyan]")
            console.print(f"      └─ becomes: [green]{response}[/green]")
            for rs, _ in handled_list[:3]:
                rel = _rel_path(rs.file, directory)
                console.print(f"      └─ raised in: [dim]{rel}:{rs.line}[/dim] ({rs.function})")
            if len(handled_list) > 3:
                console.print(f"      └─ [dim]...and {len(handled_list) - 3} more[/dim]")
        console.print()

    if result.flow.uncaught:
        reraise_patterns = {"Unknown", "e", "ex", "err", "exc", "error", "exception"}
        real_uncaught = {k: v for k, v in result.flow.uncaught.items() if k not in reraise_patterns}
        reraises = {k: v for k, v in result.flow.uncaught.items() if k in reraise_patterns}

        if real_uncaught:
            console.print("  [red]UNCAUGHT (will propagate to caller):[/red]")
            for exc_type, raise_sites in real_uncaught.items():
                evidence_list = result.flow.evidence.get(exc_type, [])
                console.print(f"    [cyan]{exc_type}[/cyan]")
                for r in raise_sites[:3]:
                    rel = _rel_path(r.file, directory)
                    matching_evidence = next(
                        (ev for ev in evidence_list if ev.raise_site.file == r.file and ev.raise_site.line == r.line),
                        None,
                    )
                    if matching_evidence and matching_evidence.call_path:
                        confidence_label = _format_confidence(matching_evidence.confidence)
                        console.print(f"      └─ raised in: [dim]{rel}:{r.line}[/dim] ({r.function}) [{confidence_label} confidence]")
                        path_parts = [_format_resolution_kind(e.resolution_kind) for e in matching_evidence.call_path[:4]]
                        if path_parts:
                            console.print(f"         call path: {' → '.join(path_parts)}")
                    else:
                        console.print(f"      └─ raised in: [dim]{rel}:{r.line}[/dim] ({r.function})")
                if len(raise_sites) > 3:
                    console.print(f"      └─ [dim]...and {len(raise_sites) - 3} more[/dim]")
            console.print()

        if reraises:
            total_reraises = sum(len(v) for v in reraises.values())
            console.print(
                f"  [dim]RE-RAISES ({total_reraises} locations - propagate caught exceptions):[/dim]"
            )
            for exc_type, raise_sites in reraises.items():
                label = "bare raise" if exc_type == "Unknown" else f"raise {exc_type}"
                console.print(f"    [dim]{label} in {len(raise_sites)} locations[/dim]")
            console.print()


def catches(
    result: CatchesResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format catches query result."""
    if output_format == "json":
        data = {
            "query": "catches",
            "exception": result.exception_type,
            "include_subclasses": result.include_subclasses,
            "local_catches": [
                {
                    "file": c.file,
                    "line": c.line,
                    "function": c.function,
                    "caught_types": c.caught_types,
                    "has_reraise": c.has_reraise,
                }
                for c in result.local_catches
            ],
            "global_handlers": [
                {
                    "file": h.file,
                    "line": h.line,
                    "function": h.function,
                    "handled_type": h.handled_type,
                }
                for h in result.global_handlers
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    total = len(result.local_catches) + len(result.global_handlers)
    if total == 0:
        console.print(f"[yellow]No catch sites found for {result.exception_type}[/yellow]")
        return

    subclass_note = " (and subclasses)" if result.include_subclasses else ""
    console.print(
        f"\n[bold]{result.exception_type}{subclass_note}[/bold] caught in {total} locations:\n"
    )

    if result.global_handlers:
        console.print("  [green]GLOBAL HANDLERS:[/green]")
        for h in result.global_handlers:
            rel = _rel_path(h.file, directory)
            console.print(
                f"    [cyan]{rel}:{h.line}[/cyan]  @errorhandler({h.handled_type}) → [green]{h.function}()[/green]"
            )
        console.print()

    if result.local_catches:
        console.print("  [blue]LOCAL TRY/EXCEPT:[/blue]")
        for c in sorted(result.local_catches, key=lambda x: (x.file, x.line)):
            rel = _rel_path(c.file, directory)
            reraise_note = " [yellow](re-raises)[/yellow]" if c.has_reraise else ""
            caught = ", ".join(c.caught_types) if c.caught_types else "bare except"
            console.print(f"    [cyan]{rel}:{c.line}[/cyan]  in [green]{c.function}()[/green]")
            console.print(f"      except {caught}{reraise_note}")
        console.print()


def trace(
    result: TraceResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format trace query result."""
    if output_format == "json":
        def node_to_dict(node: TraceNode | PolymorphicNode) -> dict:
            if isinstance(node, PolymorphicNode):
                return {
                    "function": node.function,
                    "polymorphic": True,
                    "implementations": [node_to_dict(n) for n in node.implementations],
                    "raises": node.raises,
                }
            return {
                "function": node.function,
                "qualified": node.qualified,
                "direct_raises": node.direct_raises,
                "propagated_raises": node.propagated_raises,
                "calls": [node_to_dict(c) for c in node.calls],
            }

        entrypoint_info = None
        if result.entrypoint:
            entrypoint_info = {
                "kind": result.entrypoint.kind,
                "http_method": result.entrypoint.metadata.get("http_method"),
                "http_path": result.entrypoint.metadata.get("http_path"),
            }
        data = {
            "query": "trace",
            "function": result.function_name,
            "entrypoint": entrypoint_info,
            "tree": node_to_dict(result.root) if result.root else None,
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if result.entrypoint and result.entrypoint.kind == "http_route":
        method = result.entrypoint.metadata.get("http_method", "?")
        path = result.entrypoint.metadata.get("http_path", "?")
        root_label = f"[bold green]{method}[/bold green] [bold cyan]{path}[/bold cyan]"
    else:
        root_label = f"[bold]{result.function_name}()[/bold]"

    if result.escaping_exceptions:
        exc_summary = ", ".join(sorted(e.split(".")[-1] for e in result.escaping_exceptions))
        root_label += f"  [dim]→ escapes: {exc_summary}[/dim]"

    tree = Tree(root_label)

    def build_tree(node: TraceNode | PolymorphicNode, parent: Tree) -> None:
        if isinstance(node, PolymorphicNode):
            poly_label = f"[yellow]{node.function.split('.')[-1]}()[/yellow] [dim]({len(node.implementations)} implementations)[/dim]"
            if node.raises:
                exc_list = ", ".join(sorted(e.split(".")[-1] for e in node.raises))
                poly_label += f"  [dim]→ {exc_list}[/dim]"
            poly_branch = parent.add(poly_label)
            for impl in node.implementations:
                build_tree(impl, poly_branch)
            return

        for exc in node.direct_raises:
            parent.add(f"[red]raises {exc.split('.')[-1]}[/red]")

        for child in node.calls:
            if isinstance(child, PolymorphicNode):
                build_tree(child, parent)
            else:
                label = f"[cyan]{child.function}()[/cyan]"
                if child.propagated_raises:
                    exc_list = ", ".join(sorted(e.split(".")[-1] for e in child.propagated_raises))
                    label += f"  [dim]→ {exc_list}[/dim]"
                branch = parent.add(label)
                build_tree(child, branch)

    if result.root:
        build_tree(result.root, tree)

    console.print()
    console.print(tree)
    console.print()


def subclasses(
    result: SubclassesResult,
    output_format: str,
    directory: Path,
    console: Console,
) -> None:
    """Format subclasses query result."""
    if output_format == "json":
        data = {
            "query": "subclasses",
            "class": result.class_name,
            "is_abstract": result.is_abstract,
            "abstract_methods": sorted(result.abstract_methods),
            "subclasses": [
                {
                    "name": s.name,
                    "file": s.file,
                    "is_abstract": s.is_abstract,
                }
                for s in result.subclasses
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if not result.base_class_file:
        console.print(f"[yellow]Class '{result.class_name}' not found[/yellow]")
        return

    console.print(f"\n[bold]{result.class_name}[/bold]")
    if result.is_abstract:
        console.print("[dim]  (abstract class)[/dim]")
    if result.abstract_methods:
        console.print(f"[dim]  Abstract methods: {', '.join(sorted(result.abstract_methods))}[/dim]")
    console.print()

    if not result.subclasses:
        console.print("[yellow]No subclasses found[/yellow]")
        return

    console.print(f"[bold]Subclasses ({len(result.subclasses)} total):[/bold]\n")

    for s in result.subclasses:
        abstract_note = " [dim](abstract)[/dim]" if s.is_abstract else ""
        console.print(f"  [cyan]{s.name}[/cyan]{abstract_note}")
        if s.file:
            rel = _rel_path(s.file, directory)
            console.print(f"    [dim]{rel}:{s.line}[/dim]")

    console.print()


def init_result(
    result: InitResult,
    console: Console,
) -> None:
    """Format init info (patterns detected)."""
    console.print("[bold]Detected patterns:[/bold]")
    console.print(f"  Functions:        {result.functions_count:,}")
    console.print(f"  HTTP routes:      {result.http_routes_count:,}")
    console.print(f"  CLI scripts:      {result.cli_scripts_count:,}")
    console.print(f"  Exception classes: {result.exception_classes_count:,}")
    console.print(f"  Global handlers:  {result.global_handlers_count:,}")
    if result.frameworks_detected:
        console.print(f"  Frameworks:       {', '.join(result.frameworks_detected)}")
    console.print()


def cache_stats(file_count: int, size_bytes: int, console: Console) -> None:
    """Format cache stats."""
    console.print("\n[bold]Cache Statistics:[/bold]\n")
    console.print(f"  Cached files: {file_count:,}")
    console.print(f"  Cache size:   {size_bytes / 1024:.1f} KB")
    console.print()
