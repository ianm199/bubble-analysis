"""CLI commands for Django integration (flow django ...)."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from bubble.config import load_config
from bubble.enums import Framework, OutputFormat
from bubble.extractor import extract_from_directory
from bubble.integrations import formatters
from bubble.integrations.django import DjangoIntegration
from bubble.integrations.queries import (
    audit_integration,
    list_integration_entrypoints,
    trace_routes_to_exception,
)
from bubble.models import ProgramModel

app = typer.Typer(
    name="django",
    help="Django framework-specific commands.",
    no_args_is_help=True,
)

console = Console()
integration = DjangoIntegration()


def _build_model(directory: Path, use_cache: bool = True) -> ProgramModel:
    """Build the program model from a directory."""
    with console.status(f"[bold blue]Analyzing[/bold blue] {directory.name}/..."):
        return extract_from_directory(directory, use_cache=use_cache)


def _get_django_entrypoints_and_handlers(model: ProgramModel) -> tuple[list, list]:
    """Get Django entrypoints and global handlers from the model."""
    entrypoints = [e for e in model.entrypoints if e.metadata.get("framework") == Framework.DJANGO]
    handlers = model.global_handlers
    return entrypoints, handlers


def _filter_entrypoints(entrypoints: list, filter_arg: str | None, directory: Path) -> list:
    """Filter entrypoints by file path or route path."""
    if not filter_arg:
        return entrypoints

    if filter_arg.startswith("/"):
        return [e for e in entrypoints if e.metadata.get("http_path") == filter_arg]

    filter_path = Path(filter_arg)
    if not filter_path.is_absolute():
        filter_path = directory / filter_path

    return [e for e in entrypoints if Path(directory / e.file).resolve() == filter_path.resolve()]


@app.command()
def audit(
    filter_arg: Annotated[
        str | None, typer.Argument(help="Filter by file path or route (e.g., /users)")
    ] = None,
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format")
    ] = OutputFormat.TEXT,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Check Django views for escaping exceptions.

    Scans Django views (APIView, ViewSet, @api_view) and reports which have uncaught exceptions.

    Examples:
        bubble django audit                          # All views
        bubble django audit /users                   # Views matching /users
        bubble django audit views/users.py           # Views in specific file
    """
    directory = directory.resolve()
    config = load_config(directory)
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints, handlers = _get_django_entrypoints_and_handlers(model)
    entrypoints = _filter_entrypoints(entrypoints, filter_arg, directory)

    if filter_arg and not entrypoints:
        if filter_arg.startswith("/"):
            console.print(f"[yellow]No Django views found matching {filter_arg}[/yellow]")
        else:
            console.print(f"[yellow]No Django views found in {filter_arg}[/yellow]")
        return

    result = audit_integration(model, integration, entrypoints, handlers, config=config)
    formatters.audit(result, output_format, directory, console)


@app.command(name="entrypoints")
def list_views(
    filter_arg: Annotated[
        str | None, typer.Argument(help="Filter by file path or route (e.g., /users)")
    ] = None,
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format")
    ] = OutputFormat.TEXT,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """List Django views (APIView, ViewSet, @api_view).

    Examples:
        bubble django entrypoints                    # All views
        bubble django entrypoints /users             # Views matching /users
        bubble django entrypoints views/users.py     # Views in specific file
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints, _ = _get_django_entrypoints_and_handlers(model)
    entrypoints = _filter_entrypoints(entrypoints, filter_arg, directory)
    result = list_integration_entrypoints(integration, entrypoints)
    formatters.entrypoints(result, output_format, directory, console)


@app.command(name="routes-to")
def routes_to(
    exception_type: Annotated[str, typer.Argument(help="Exception type to trace")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    include_subclasses: Annotated[
        bool, typer.Option("--include-subclasses", "-s", help="Include subclasses")
    ] = False,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format")
    ] = OutputFormat.TEXT,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Trace which Django views can trigger a given exception.

    Example:
        flow django routes-to ValueError
        flow django routes-to DatabaseError -s
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints, _ = _get_django_entrypoints_and_handlers(model)
    result = trace_routes_to_exception(
        model, integration, entrypoints, exception_type, include_subclasses
    )
    formatters.routes_to(result, output_format, directory, console)
