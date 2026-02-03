"""CLI commands for CLI scripts integration (flow cli ...)."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from bubble.enums import EntrypointKind, OutputFormat
from bubble.extractor import extract_from_directory
from bubble.integrations import formatters
from bubble.integrations.cli_scripts import CLIScriptsIntegration
from bubble.integrations.queries import (
    audit_integration,
    list_integration_entrypoints,
    trace_routes_to_exception,
)
from bubble.models import ProgramModel
from bubble.stubs import load_stubs

app = typer.Typer(
    name="cli",
    help="CLI scripts (if __name__ == '__main__') commands.",
    no_args_is_help=True,
)

console = Console()
integration = CLIScriptsIntegration()


def _build_model(directory: Path, use_cache: bool = True) -> ProgramModel:
    """Build the program model from a directory."""
    with console.status(f"[bold blue]Analyzing[/bold blue] {directory.name}/..."):
        return extract_from_directory(directory, use_cache=use_cache)


def _get_cli_entrypoints(model: ProgramModel) -> list:
    """Get CLI script entrypoints from the model."""
    return [e for e in model.entrypoints if e.kind == EntrypointKind.CLI_SCRIPT]


@app.command()
def audit(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Check CLI scripts for escaping exceptions.

    Scans every CLI script entrypoint, reports which have uncaught exceptions.

    Example:
        flow cli audit
        flow cli audit -d /path/to/project
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints = _get_cli_entrypoints(model)
    stub_library = load_stubs(directory)
    result = audit_integration(
        model, integration, entrypoints, [], stub_library=stub_library
    )
    formatters.audit(result, OutputFormat(output_format), directory, console)


@app.command(name="entrypoints")
def list_scripts(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """List CLI script entrypoints.

    Example:
        flow cli entrypoints
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints = _get_cli_entrypoints(model)
    result = list_integration_entrypoints(integration, entrypoints)
    formatters.entrypoints(result, OutputFormat(output_format), directory, console)


@app.command(name="scripts-to")
def scripts_to(
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
    """Trace which CLI scripts can trigger a given exception.

    Example:
        flow cli scripts-to ValueError
        flow cli scripts-to FileNotFoundError -s
    """
    directory = directory.resolve()
    model = _build_model(directory, use_cache=not no_cache)
    entrypoints = _get_cli_entrypoints(model)
    result = trace_routes_to_exception(
        model, integration, entrypoints, exception_type, include_subclasses
    )
    formatters.routes_to(result, OutputFormat(output_format), directory, console)
