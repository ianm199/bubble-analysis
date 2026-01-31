"""Command-line interface for flow analysis.

This module handles argument parsing only. Business logic lives in queries.py,
output formatting lives in formatters.py.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from flow import formatters, queries
from flow.enums import OutputFormat, ResolutionMode
from flow.extractor import extract_from_directory
from flow.models import ProgramModel

HELP_TEXT = """Exception flow analysis for Python codebases.

**Quick start:**
```
flow flask audit              # Check Flask routes for escaping exceptions
flow fastapi audit            # Check FastAPI routes for escaping exceptions
flow cli audit                # Check CLI scripts for escaping exceptions
flow escapes <function>       # Deep dive into one function
```

**Typical workflow:**
```
flow flask entrypoints        # See what Flask routes exist
flow flask audit              # Find which have uncaught exceptions
flow escapes <function>       # Investigate a specific one
flow trace <function>         # Visualize the call tree
```

**Core commands (framework-agnostic):**
```
flow raises <Exception>       # Where is this raised?
flow escapes <function>       # What can escape from this function?
flow callers <function>       # Who calls this?
flow catches <Exception>      # Where is this caught?
flow trace <function>         # Call tree visualization
flow exceptions               # Exception hierarchy
flow stats                    # Codebase statistics
```

**Framework-specific commands:**
```
flow flask audit/entrypoints/routes-to
flow fastapi audit/entrypoints/routes-to
flow cli audit/entrypoints/scripts-to
```

**All commands support:** `-f json` for structured output
"""

app = typer.Typer(
    name="flow",
    help=HELP_TEXT,
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

console = Console()


def _register_integration_subcommands() -> None:
    """Register integration CLI subcommands."""
    from flow.integrations import get_registered_integrations, load_builtin_integrations

    load_builtin_integrations()

    for integration in get_registered_integrations():
        app.add_typer(integration.cli_app, name=integration.name)


_register_integration_subcommands()


def build_model(directory: Path, use_cache: bool = True) -> ProgramModel:
    """Build the program model from a directory."""
    with console.status(f"[bold blue]Analyzing[/bold blue] {directory.name}/..."):
        return extract_from_directory(directory, use_cache=use_cache)


@app.command()
def raises(
    exception_type: Annotated[str, typer.Argument(help="Exception type to search for")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    include_subclasses: Annotated[
        bool, typer.Option("--include-subclasses", "-s", help="Include subclasses")
    ] = False,
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Find all places where an exception is raised."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_raises(model, exception_type, include_subclasses)
    formatters.raises(result, OutputFormat(output_format), directory, console)


@app.command()
def exceptions(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """List the exception hierarchy in the codebase."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_exceptions(model)
    formatters.exceptions(result, OutputFormat(output_format), directory, console)


@app.command()
def stats(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Show statistics about the codebase."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.get_stats(model)
    formatters.stats(result, OutputFormat(output_format), console)


@app.command()
def callers(
    function_name: Annotated[str, typer.Argument(help="Function name to find callers of")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    show_resolution: Annotated[
        bool, typer.Option("--show-resolution", "-r", help="Show resolution details")
    ] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Find all places where a function is called."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_callers(model, function_name)
    formatters.callers(result, OutputFormat(output_format), directory, console, show_resolution)


@app.command()
def escapes(
    function_name: Annotated[str, typer.Argument(help="Function or route to analyze")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="High precision - only resolved calls")
    ] = False,
    aggressive: Annotated[
        bool, typer.Option("--aggressive", help="High recall - include fuzzy matches")
    ] = False,
) -> None:
    """Show which exceptions can escape from a function.

    This is the core (framework-agnostic) version. For framework-aware auditing,
    use the integration commands (e.g., flow flask audit).
    """
    from flow.config import load_config

    directory = directory.resolve()
    config = load_config(directory)

    if strict:
        resolution_mode = ResolutionMode.STRICT
    elif aggressive:
        resolution_mode = ResolutionMode.AGGRESSIVE
    else:
        resolution_mode = ResolutionMode(config.resolution_mode)

    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_escapes(model, function_name, resolution_mode=resolution_mode)
    formatters.escapes(result, OutputFormat(output_format), directory, console)


@app.command()
def catches(
    exception_type: Annotated[str, typer.Argument(help="Exception type to search for")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    include_subclasses: Annotated[
        bool, typer.Option("--include-subclasses", "-s", help="Include subclasses")
    ] = False,
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Find all places where an exception type is caught."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_catches(model, exception_type, include_subclasses)
    formatters.catches(result, OutputFormat(output_format), directory, console)


@app.command()
def cache(
    action: Annotated[str, typer.Argument(help="Action: clear or stats")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to manage cache for")
    ] = Path("."),
) -> None:
    """Manage the extraction cache."""
    from flow.cache import FileCache

    directory = directory.resolve()
    cache_dir = directory / ".flow"
    cache_file = cache_dir / "cache.sqlite"

    if action == "clear":
        if cache_file.exists():
            cache_file.unlink()
            console.print("[green]Cache cleared[/green]")
        else:
            console.print("[yellow]No cache to clear[/yellow]")

    elif action == "stats":
        if not cache_file.exists():
            console.print("[yellow]No cache exists[/yellow]")
            return

        fc = FileCache(cache_dir)
        stats_data = fc.stats()
        fc.close()
        formatters.cache_stats(stats_data["file_count"], stats_data["size_bytes"], console)

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Valid actions: clear, stats")
        raise typer.Exit(1)


@app.command()
def trace(
    function_name: Annotated[str, typer.Argument(help="Function or route to trace")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    depth: Annotated[int, typer.Option("--depth", help="Maximum call depth")] = 10,
    show_all: Annotated[
        bool, typer.Option("--all", "-a", help="Show all calls, not just exception-raising paths")
    ] = False,
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Visualize exception flow as a call tree."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.trace_function(model, function_name, depth, show_all)
    formatters.trace(result, OutputFormat(output_format), directory, console)


@app.command()
def subclasses(
    class_name: Annotated[str, typer.Argument(help="Base class name to find subclasses of")],
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to analyze")
    ] = Path("."),
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable caching")] = False,
) -> None:
    """Show all subclasses of a class and their abstract method implementations."""
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_subclasses(model, class_name)
    formatters.subclasses(result, OutputFormat(output_format), directory, console)


@app.command()
def init(
    directory: Annotated[
        Path, typer.Option("--directory", "-d", help="Directory to initialize")
    ] = Path("."),
) -> None:
    """Initialize .flow/ directory with detector templates."""
    directory = directory.resolve()
    flow_dir = directory / ".flow"
    detectors_dir = flow_dir / "detectors"

    if flow_dir.exists():
        console.print(f"[yellow].flow/ directory already exists at {flow_dir}[/yellow]")
        console.print("[dim]Delete it first if you want to reinitialize.[/dim]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Initializing flow analysis for {directory.name}/[/bold]\n")

    with console.status("[bold blue]Analyzing codebase patterns...[/bold blue]"):
        model = build_model(directory, use_cache=False)

    result = queries.get_init_info(model, directory.name)
    formatters.init_result(result, console)

    flow_dir.mkdir(parents=True, exist_ok=True)
    detectors_dir.mkdir(parents=True, exist_ok=True)

    config_content = f"""# Flow analysis configuration for {directory.name}
version: "0.1"

# Frameworks detected (used for default detectors)
frameworks:
{chr(10).join(f"  - {f.lower()}" for f in result.frameworks_detected) if result.frameworks_detected else "  # none detected"}

# Directories to exclude from analysis
exclude:
  - __pycache__
  - .venv
  - venv
  - site-packages
  - node_modules
  - .git
  - dist
  - build
  - tests
  - test

# Base exception classes to track (add your custom exceptions here)
exception_bases:
  - Exception
"""

    (flow_dir / "config.yaml").write_text(config_content)
    console.print("  [green]Created[/green] .flow/config.yaml")

    example_detector = '''"""Example custom detector for project-specific patterns."""

from flow.protocols import EntrypointDetector
from flow.models import Entrypoint


class ExampleCeleryTaskDetector(EntrypointDetector):
    """Example: Detects Celery task decorators as entrypoints."""

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        return []
'''

    (detectors_dir / "_example.py").write_text(example_detector)
    console.print("  [green]Created[/green] .flow/detectors/_example.py")

    readme_content = """# Custom Detectors

Create Python files here to detect project-specific patterns.
See _example.py for a template.
"""

    (detectors_dir / "README.md").write_text(readme_content)
    console.print("  [green]Created[/green] .flow/detectors/README.md")

    console.print()
    console.print("[bold green]Initialization complete![/bold green]")
    console.print()
    console.print("[dim]Next steps:[/dim]")
    console.print("  1. Review .flow/config.yaml")
    console.print(
        "  2. Run 'flow flask entrypoints' or 'flow fastapi entrypoints' to verify detection"
    )
    console.print()


@app.command()
def stubs(
    action: Annotated[str, typer.Argument(help="Action: list, init, or validate")],
    library: Annotated[str | None, typer.Argument(help="Library name for init action")] = None,
    directory: Annotated[Path, typer.Option("--directory", "-d", help="Project directory")] = Path(
        "."
    ),
) -> None:
    """Manage exception stubs for external libraries."""
    import shutil

    from flow.stubs import load_stubs, validate_stub_file

    directory = directory.resolve()
    builtin_dir = Path(__file__).parent / "stubs"
    user_dir = directory / ".flow" / "stubs"

    if action == "list":
        stub_library = load_stubs(directory)
        if not stub_library.stubs:
            console.print("[yellow]No stubs loaded[/yellow]")
            console.print()
            console.print("[dim]Built-in stubs available:[/dim]")
            if builtin_dir.exists():
                for yaml_file in sorted(builtin_dir.glob("*.yaml")):
                    console.print(f"  - {yaml_file.stem}")
            return

        console.print("\n[bold]Loaded exception stubs:[/bold]\n")
        for module, functions in sorted(stub_library.stubs.items()):
            exc_count = sum(len(excs) for excs in functions.values())
            console.print(
                f"  [cyan]{module}[/cyan]: {len(functions)} functions, {exc_count} exceptions"
            )
        console.print()

    elif action == "init":
        if not library:
            console.print("[red]Library name required for init action[/red]")
            console.print("[dim]Example: flow stubs init requests[/dim]")
            raise typer.Exit(1)

        source_file = builtin_dir / f"{library}.yaml"
        if not source_file.exists():
            console.print(f"[red]No built-in stub for '{library}'[/red]")
            console.print("[dim]Available stubs:[/dim]")
            if builtin_dir.exists():
                for yaml_file in sorted(builtin_dir.glob("*.yaml")):
                    console.print(f"  - {yaml_file.stem}")
            raise typer.Exit(1)

        user_dir.mkdir(parents=True, exist_ok=True)
        dest_file = user_dir / f"{library}.yaml"
        shutil.copy(source_file, dest_file)
        console.print(f"[green]Copied {library}.yaml to .flow/stubs/[/green]")
        console.print("[dim]Edit this file to customize exception declarations.[/dim]")

    elif action == "validate":
        errors_found = False
        for stub_dir in [builtin_dir, user_dir]:
            if stub_dir.exists():
                for yaml_file in stub_dir.glob("*.yaml"):
                    errors = validate_stub_file(yaml_file)
                    if errors:
                        errors_found = True
                        console.print(f"[red]Errors in {yaml_file.name}:[/red]")
                        for error in errors:
                            console.print(f"  - {error}")
                    else:
                        console.print(f"[green]v[/green] {yaml_file.name}")

        if not errors_found:
            console.print("\n[green]All stub files are valid[/green]")

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Valid actions: list, init, validate")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
