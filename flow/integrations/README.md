# Framework Integrations

Flow uses a plugin architecture for framework support. Each integration teaches Flow how to detect entrypoints (HTTP routes, CLI scripts) and exception handlers for a specific framework.

## Philosophy: AI-Friendly Extensibility

Traditional static analysis tools require deep expertise to extend. Flow takes a different approach: **integrations are simple enough that an AI agent can write one in minutes**.

This isn't theoretical—the Django integration was written by Claude in a single session:
- ~350 lines of straightforward Python
- Follows the same pattern as Flask/FastAPI
- Immediately detected 89 views in an 82k LOC codebase

### Why This Matters

New Python frameworks appear constantly. Instead of waiting for tool maintainers to add support, you can:

1. Ask an AI agent: "Add support for [framework X] to Flow"
2. Point it at this documentation and an example integration
3. Get working analysis for your framework in minutes

The architecture deliberately minimizes what you need to know:
- No compiler theory
- No complex type systems
- Just "find decorated functions" and "map exceptions to responses"

## Architecture Overview

```
flow/integrations/
├── __init__.py          # Registry and loading
├── base.py              # Protocol definitions (Entrypoint, GlobalHandler, Integration)
├── models.py            # Shared data structures
├── queries.py           # Shared analysis logic (audit, routes-to, etc.)
├── formatters.py        # Shared output formatting
│
├── flask/               # Flask integration
│   ├── detector.py      # AST visitors for @app.route, @errorhandler
│   ├── semantics.py     # HTTPException → HTTP response mappings
│   └── cli.py           # `flow flask` subcommands
│
├── fastapi/             # FastAPI integration
│   ├── detector.py      # AST visitors for @router.get, @app.exception_handler
│   ├── semantics.py     # Exception → HTTP response mappings
│   └── cli.py           # `flow fastapi` subcommands
│
├── django/              # Django/DRF integration
│   ├── detector.py      # AST visitors for APIView, ViewSet, @api_view
│   ├── semantics.py     # Http404, PermissionDenied → HTTP response mappings
│   └── cli.py           # `flow django` subcommands
│
└── cli_scripts/         # CLI script integration (if __name__ == "__main__")
    ├── detector.py
    └── cli.py
```

## The Integration Protocol

Every integration implements this interface (defined in `base.py`):

```python
class Integration(Protocol):
    @property
    def name(self) -> str:
        """Integration name (e.g., "flask", "django")."""
        ...

    @property
    def cli_app(self) -> typer.Typer:
        """CLI subcommands for this integration."""
        ...

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        """Find HTTP routes, CLI scripts, etc. in source code."""
        ...

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Find exception handlers (@errorhandler, middleware, etc.)."""
        ...

    def get_exception_response(self, exception_type: str) -> str | None:
        """Map exception to HTTP response (e.g., "NotFound" → "HTTP 404")."""
        ...
```

## Creating a New Integration

### Step 1: Create the Directory Structure

```
flow/integrations/myframework/
├── __init__.py      # Integration class
├── detector.py      # AST visitors
├── semantics.py     # Exception mappings
└── cli.py           # CLI commands
```

### Step 2: Write the Detector

The detector uses [libcst](https://libcst.readthedocs.io/) to walk the AST. Here's a minimal example:

```python
# detector.py
import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from flow.integrations.base import Entrypoint

class MyFrameworkRouteVisitor(cst.CSTVisitor):
    """Detects @myframework.route decorators."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            if self._is_route_decorator(decorator):
                pos = self.get_metadata(PositionProvider, node)
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=node.name.value,
                        line=pos.start.line,
                        kind="http_route",
                        metadata={"framework": "myframework"},
                    )
                )
        return True

    def _is_route_decorator(self, decorator: cst.Decorator) -> bool:
        # Check if decorator matches @myframework.route or similar
        ...

def detect_myframework_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    try:
        module = cst.parse_module(source)
        wrapper = MetadataWrapper(module)
        visitor = MyFrameworkRouteVisitor(file_path)
        wrapper.visit(visitor)
        return visitor.entrypoints
    except Exception:
        return []
```

### Step 3: Define Exception Mappings

```python
# semantics.py
EXCEPTION_RESPONSES: dict[str, str] = {
    "myframework.NotFoundError": "HTTP 404",
    "myframework.AuthError": "HTTP 401",
    "myframework.ValidationError": "HTTP 400",
}
```

### Step 4: Create the Integration Class

```python
# __init__.py
import typer
from flow.integrations.base import Entrypoint, GlobalHandler
from flow.integrations.myframework.detector import detect_myframework_entrypoints
from flow.integrations.myframework.semantics import EXCEPTION_RESPONSES
from flow.integrations.models import IntegrationData

class MyFrameworkIntegration:
    @property
    def name(self) -> str:
        return "myframework"

    @property
    def cli_app(self) -> typer.Typer:
        from flow.integrations.myframework.cli import app
        return app

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        return detect_myframework_entrypoints(source, file_path)

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        return []  # Implement if framework has global handlers

    def get_exception_response(self, exception_type: str) -> str | None:
        exc_simple = exception_type.split(".")[-1]
        for handled_type, response in EXCEPTION_RESPONSES.items():
            if exc_simple == handled_type.split(".")[-1]:
                return response
        return None

    def extract_integration_data(self, source: str, file_path: str) -> IntegrationData:
        return IntegrationData(
            entrypoints=self.detect_entrypoints(source, file_path),
            global_handlers=self.detect_global_handlers(source, file_path),
        )
```

### Step 5: Add CLI Commands

```python
# cli.py
from pathlib import Path
from typing import Annotated
import typer
from rich.console import Console
from flow.extractor import extract_from_directory
from flow.integrations import formatters
from flow.integrations.myframework import MyFrameworkIntegration
from flow.integrations.queries import audit_integration, list_integration_entrypoints

app = typer.Typer(name="myframework", help="MyFramework commands.")
console = Console()
integration = MyFrameworkIntegration()

@app.command()
def audit(
    directory: Annotated[Path, typer.Option("-d")] = Path("."),
    output_format: Annotated[str, typer.Option("-f")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
) -> None:
    """Check MyFramework routes for escaping exceptions."""
    model = extract_from_directory(directory.resolve(), use_cache=not no_cache)
    entrypoints = [e for e in model.entrypoints if e.metadata.get("framework") == "myframework"]
    result = audit_integration(model, integration, entrypoints, model.global_handlers)
    formatters.audit(result, output_format, directory, console)

@app.command(name="entrypoints")
def list_routes(
    directory: Annotated[Path, typer.Option("-d")] = Path("."),
    output_format: Annotated[str, typer.Option("-f")] = "text",
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
) -> None:
    """List MyFramework routes."""
    model = extract_from_directory(directory.resolve(), use_cache=not no_cache)
    entrypoints = [e for e in model.entrypoints if e.metadata.get("framework") == "myframework"]
    result = list_integration_entrypoints(integration, entrypoints)
    formatters.entrypoints(result, output_format, directory, console)
```

### Step 6: Register the Integration

In `flow/integrations/__init__.py`:

```python
def load_builtin_integrations() -> None:
    from flow.integrations.myframework import MyFrameworkIntegration
    register_integration(MyFrameworkIntegration())
```

In `flow/extractor.py`, add framework detection:

```python
def _detect_framework(self, module_name: str) -> None:
    if "myframework" in module_name.lower():
        self.detected_frameworks.add("myframework")
```

In `flow/detectors.py`, add the detector:

```python
from flow.integrations.myframework.detector import detect_myframework_entrypoints

def detect_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    entrypoints.extend(detect_myframework_entrypoints(source, file_path))
```

## What You Get For Free

Once registered, your integration automatically gets:

- **Exception propagation analysis** - Flow traces which exceptions can escape from your entrypoints
- **Call graph traversal** - Understands function calls, method resolution, imports
- **Confidence scoring** - Distinguishes resolved calls from heuristic fallbacks
- **Caching** - SQLite-based caching for fast re-analysis
- **Multiple output formats** - Text and JSON output
- **Routes-to analysis** - "Which endpoints can trigger this exception?"

The heavy lifting is in `flow/integrations/queries.py` and `flow/propagation.py`—your integration just needs to identify the entrypoints.

## Real-World Example: Django Integration

The Django integration was added to analyze Label Studio (82k LOC). Key decisions:

**What to detect:**
- DRF view classes (APIView, ViewSet, generics.*)
- @api_view decorated functions
- NOT traditional Django function views (could be added)

**Exception mappings:**
- Django: Http404 → 404, PermissionDenied → 403
- DRF: ValidationError → 400, NotAuthenticated → 401, Throttled → 429

**What we skipped (for now):**
- URL pattern parsing (shows "?" instead of actual paths)
- Middleware-based exception handling
- Custom exception handler registration

The integration works well enough to find real issues, and can be enhanced incrementally.

## Tips for AI Agents

If you're an AI agent creating a new integration:

1. **Start by reading an existing integration** - Flask is the simplest, Django shows class-based detection
2. **Identify the decorator/class patterns** - What makes a function an HTTP endpoint in this framework?
3. **Find the exception mappings** - What exceptions does the framework catch and convert to HTTP responses?
4. **Test on a real codebase** - Clone a popular project using the framework and verify detection works
5. **Don't over-engineer** - Basic detection that finds 80% of routes is more valuable than complex detection that takes days to build

The goal is useful analysis, not perfect analysis. Flow's name-based fallback resolution means even imperfect entrypoint detection provides value.
