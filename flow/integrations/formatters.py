"""Output formatters for integration-specific results.

Shared formatting logic for audit, entrypoints, and routes-to results.
"""

import json
from pathlib import Path

from rich.console import Console

from flow.enums import EntrypointKind, OutputFormat
from flow.integrations.models import AuditResult, EntrypointsResult, RoutesToResult


def _rel_path(file: str, directory: Path) -> str:
    """Get relative path for display."""
    if file.startswith(str(directory)):
        return str(Path(file).relative_to(directory))
    return file


def audit(
    result: AuditResult,
    output_format: OutputFormat,
    directory: Path,
    console: Console,
) -> None:
    """Format audit result for an integration."""
    if output_format == OutputFormat.JSON:
        data = {
            "query": "audit",
            "integration": result.integration_name,
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
                        exc_type: [
                            {"file": r.file, "line": r.line, "function": r.function}
                            for r in raises_list
                        ]
                        for exc_type, raises_list in issue.uncaught.items()
                    },
                }
                for issue in result.issues
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if result.total_entrypoints == 0:
        console.print(f"[yellow]No {result.integration_name} entrypoints found[/yellow]")
        return

    console.print(
        f"\n[bold]Scanning {result.total_entrypoints} {result.integration_name} entrypoints...[/bold]\n"
    )

    if result.issues:
        console.print(
            f"[red bold]{len(result.issues)} entrypoints have uncaught exceptions:[/red bold]\n"
        )

        for issue in result.issues:
            ep = issue.entrypoint
            if ep.kind == EntrypointKind.HTTP_ROUTE:
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
                    console.print(f"    {exc_simple} [dim]({rel}:{rs.line})[/dim]")
                if len(raise_sites) > 2:
                    console.print(f"    [dim]...and {len(raise_sites) - 2} more[/dim]")
            console.print()
    else:
        console.print("[green bold]All entrypoints have exception handlers[/green bold]\n")

    if result.clean_count > 0:
        console.print(
            f"[green]{result.clean_count} entrypoints fully covered by exception handlers[/green]\n"
        )


def entrypoints(
    result: EntrypointsResult,
    output_format: OutputFormat,
    directory: Path,
    console: Console,
) -> None:
    """Format entrypoints result for an integration."""
    if output_format == OutputFormat.JSON:
        data = {
            "query": "entrypoints",
            "integration": result.integration_name,
            "count": len(result.entrypoints),
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
                for e in result.entrypoints
            ],
        }
        console.print_json(json.dumps(data, indent=2))
        return

    if not result.entrypoints:
        console.print(f"[yellow]No {result.integration_name} entrypoints found[/yellow]")
        return

    http_routes = [e for e in result.entrypoints if e.kind == EntrypointKind.HTTP_ROUTE]
    cli_scripts = [e for e in result.entrypoints if e.kind == EntrypointKind.CLI_SCRIPT]
    other = [
        e
        for e in result.entrypoints
        if e.kind not in (EntrypointKind.HTTP_ROUTE, EntrypointKind.CLI_SCRIPT)
    ]

    if http_routes:
        console.print(
            f"\n[bold]{result.integration_name.title()} Routes ({len(http_routes)} total):[/bold]\n"
        )
        sorted_routes = sorted(
            http_routes,
            key=lambda e: (
                e.metadata.get("http_path", ""),
                e.metadata.get("http_method", ""),
            ),
        )
        for e in sorted_routes:
            method = e.metadata.get("http_method", "?")
            path = e.metadata.get("http_path", "?")
            rel = _rel_path(e.file, directory)
            console.print(
                f"  [green]{method:6}[/green] [cyan]{path:40}[/cyan] {rel}:[bold]{e.function}[/bold]"
            )
        console.print()

    if cli_scripts:
        console.print(f"\n[bold]CLI Scripts ({len(cli_scripts)} total):[/bold]\n")
        sorted_scripts = sorted(cli_scripts, key=lambda e: e.file)
        for e in sorted_scripts:
            rel = _rel_path(e.file, directory)
            if e.metadata.get("inline"):
                console.print(
                    f"  [magenta]{rel}[/magenta]:[bold]{e.line}[/bold] [dim](inline code)[/dim]"
                )
            else:
                console.print(f"  [magenta]{rel}[/magenta]:[bold]{e.function}[/bold]()")
        console.print()

    if other:
        console.print(f"\n[bold]Other ({len(other)} total):[/bold]\n")
        for e in sorted(other, key=lambda x: x.file):
            rel = _rel_path(e.file, directory)
            console.print(f"  [yellow]{rel}[/yellow]:[bold]{e.function}[/bold]()")
        console.print()


def routes_to(
    result: RoutesToResult,
    output_format: OutputFormat,
    directory: Path,
    console: Console,
) -> None:
    """Format routes-to result for an integration."""
    if output_format == OutputFormat.JSON:
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
            "query": "routes-to",
            "integration": result.integration_name,
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
        f"\n[bold]{result.integration_name.title()} routes that can reach "
        f"{result.exception_type}{subclass_note}:[/bold]\n"
    )

    for trace in result.traces:
        rel = _rel_path(trace.raise_site.file, directory)

        if not trace.entrypoints:
            console.print(
                f"  [cyan]{rel}:{trace.raise_site.line}[/cyan] in "
                f"[green]{trace.raise_site.function}()[/green]"
            )
            console.print(
                f"    [dim]No {result.integration_name} entrypoints found in call chain[/dim]\n"
            )
            continue

        console.print(
            f"  [cyan]{rel}:{trace.raise_site.line}[/cyan] in "
            f"[green]{trace.raise_site.function}()[/green]"
        )
        for e in trace.entrypoints:
            method = e.metadata.get("http_method", "?")
            path = e.metadata.get("http_path", "?")
            console.print(f"    -> [green]{method}[/green] [cyan]{path}[/cyan] ({e.function})")
        console.print()
