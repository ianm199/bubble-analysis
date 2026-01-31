"""CLI commands for FastAPI integration (flow fastapi ...)."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from flow.enums import Framework, OutputFormat
from flow.extractor import extract_from_directory
from flow.integrations import formatters
from flow.integrations.fastapi import FastAPIIntegration
from flow.integrations.queries import (
    audit_integration,
    list_integration_entrypoints,
    trace_routes_to_exception,
)
from flow.models import ProgramModel

app = typer.Typer(
    name="fastapi",
    help="FastAPI framework-specific commands.",
    no_args_is_help=True,
)

console = Console()
integration = FastAPIIntegration()


def _build_model(directory: Path, use_cache: bool = True) -> ProgramModel:
    """Build the program model from a directory."""
    with console.status(f"[bold blue]Analyzing[/bold blue] {directory.name}/..."):
        return extract_from_directory(directory, use_cache=use_cache)


def _get_fastapi_entrypoints_and_handlers(model: ProgramModel) -> tuple[list, list]:
    """Get FastAPI entrypoints and global handlers from the model."""
    entrypoints = [e for e in model.entrypoints if e.metadata.get("framework") == Framework.FASTAPI]
    handlers = model.global_handlers
    return entrypoints, handlers


@app.command()
def audit(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Check FastAPI routes for escaping exceptions.

    Scans every FastAPI HTTP route, reports which have uncaught exceptions.

    Example:
        flow fastapi audit
        flow fastapi audit -d /path/to/project
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints, handlers = _get_fastapi_entrypoints_and_handlers(model)
    result = audit_integration(model, integration, entrypoints, handlers)
    formatters.audit(result, OutputFormat(output_format), directory, console)


@app.command(name="entrypoints")
def list_routes(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """List FastAPI HTTP routes.

    Example:
        flow fastapi entrypoints
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints, _ = _get_fastapi_entrypoints_and_handlers(model)
    result = list_integration_entrypoints(integration, entrypoints)
    formatters.entrypoints(result, OutputFormat(output_format), directory, console)


@app.command(name="routes-to")
def routes_to(
    exception_type: Annotated[str, typer.Argument(help="Exception type to trace")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    include_subclasses: Annotated[
        bool, typer.Option("--include-subclasses", "-s", help="Include subclasses")
    ] = False,
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Trace which FastAPI routes can trigger a given exception.

    Example:
        flow fastapi routes-to ValueError
        flow fastapi routes-to ValidationError -s
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints, _ = _get_fastapi_entrypoints_and_handlers(model)
    result = trace_routes_to_exception(
        model, integration, entrypoints, exception_type, include_subclasses
    )
    formatters.routes_to(result, OutputFormat(output_format), directory, console)
