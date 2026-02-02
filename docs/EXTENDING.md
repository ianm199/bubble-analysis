# Extending Bubble

This guide explains how to extend bubble-analysis for custom frameworks, queue systems, or internal patterns.

## The Mental Model

Bubble traces exceptions from where they're raised to where they're caught. The goal: **find exceptions that can escape your application boundaries**.

```
                    Application Boundary
                           │
    raise ValueError()     │     HTTP 500 (unhandled)
           │               │           ▲
           ▼               │           │
    ┌─────────────┐        │     ┌─────┴─────┐
    │  service.py │───────────────▶│  route.py │
    └─────────────┘        │     └───────────┘
                           │           │
                           │     @errorhandler(ValueError)
                           │           │
                           │           ▼
                           │     HTTP 400 (handled)
```

For this to work, bubble needs to know:

1. **Where are the boundaries?** (entrypoints)
2. **What catches exceptions at those boundaries?** (global handlers)
3. **Which exceptions does the framework handle automatically?** (semantics)

Built-in integrations handle Flask, FastAPI, and CLI scripts. For anything else, you extend bubble.

## What You Can Extend

| Extension Point | What it does | Example use case |
|-----------------|--------------|------------------|
| Entrypoint Detector | Finds application boundaries | Celery tasks, Django views, gRPC handlers |
| Handler Detector | Finds global exception handlers | Custom middleware, error decorators |
| Full Integration | Complete framework support | Django REST Framework, Airflow |

## Extension Point 1: Entrypoint Detectors

An entrypoint is where external input enters your program. Bubble needs to know these to report "what can escape from this endpoint?"

### The Protocol

```python
from bubble.protocols import EntrypointDetector
from bubble.integrations.base import Entrypoint
from bubble.enums import EntrypointKind

class MyDetector(EntrypointDetector):
    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Find entrypoints in a Python source file."""
        ...
```

### What You Return

```python
Entrypoint(
    file="tasks.py",           # Relative path
    function="process_order",  # Function name (Class.method for methods)
    line=42,                   # Line number
    kind=EntrypointKind.OTHER, # HTTP_ROUTE, CLI_SCRIPT, or OTHER
    metadata={                 # Framework-specific info
        "framework": "celery",
        "queue": "orders",
    },
)
```

### Example: Celery Task Detector

```python
import libcst as cst
from bubble.protocols import EntrypointDetector
from bubble.integrations.base import Entrypoint
from bubble.enums import EntrypointKind


class CeleryTaskDetector(EntrypointDetector):
    """Detect Celery tasks as entrypoints."""

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        try:
            module = cst.parse_module(source)
        except cst.ParserSyntaxError:
            return []

        visitor = CeleryTaskVisitor(file_path)
        module.walk(visitor)
        return visitor.entrypoints


class CeleryTaskVisitor(cst.CSTVisitor):
    """AST visitor that finds @celery.task and @app.task decorators."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            if self._is_celery_task(decorator):
                pos = self.get_metadata(cst.metadata.PositionProvider, node)
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=node.name.value,
                        line=pos.start.line if pos else 0,
                        kind=EntrypointKind.OTHER,
                        metadata={
                            "framework": "celery",
                            "queue": self._extract_queue(decorator),
                        },
                    )
                )
        return True

    def _is_celery_task(self, decorator: cst.Decorator) -> bool:
        dec = decorator.decorator
        if isinstance(dec, cst.Attribute):
            return dec.attr.value == "task"
        if isinstance(dec, cst.Call) and isinstance(dec.func, cst.Attribute):
            return dec.func.attr.value == "task"
        return False

    def _extract_queue(self, decorator: cst.Decorator) -> str:
        # Extract queue name from @app.task(queue="orders")
        ...
        return "default"
```

### Installing Custom Detectors

Place your detector in `.flow/detectors/`:

```
your-project/
├── .flow/
│   └── detectors/
│       └── celery.py    # Your detector
├── tasks.py
└── ...
```

Bubble auto-loads detectors from `.flow/detectors/` on every run.

## Extension Point 2: Handler Detectors

Global handlers catch exceptions at the application boundary. Without knowing about them, bubble reports false positives.

### The Protocol

```python
from bubble.protocols import GlobalHandlerDetector
from bubble.integrations.base import GlobalHandler

class MyHandlerDetector(GlobalHandlerDetector):
    def detect(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Find global exception handlers in a Python source file."""
        ...
```

### What You Return

```python
GlobalHandler(
    file="errors.py",          # Relative path
    function="handle_db_error", # Handler function name
    line=15,                   # Line number
    handled_type="DatabaseError", # Exception class caught
)
```

### Example: Custom Decorator Handler Detector

```python
import libcst as cst
from bubble.protocols import GlobalHandlerDetector
from bubble.integrations.base import GlobalHandler


class ErrorDecoratorDetector(GlobalHandlerDetector):
    """Detect @handle_errors(ExceptionType) decorators."""

    def detect(self, source: str, file_path: str) -> list[GlobalHandler]:
        try:
            module = cst.parse_module(source)
        except cst.ParserSyntaxError:
            return []

        visitor = ErrorDecoratorVisitor(file_path)
        module.walk(visitor)
        return visitor.handlers


class ErrorDecoratorVisitor(cst.CSTVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.handlers: list[GlobalHandler] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            exc_type = self._extract_handled_type(decorator)
            if exc_type:
                pos = self.get_metadata(cst.metadata.PositionProvider, node)
                self.handlers.append(
                    GlobalHandler(
                        file=self.file_path,
                        function=node.name.value,
                        line=pos.start.line if pos else 0,
                        handled_type=exc_type,
                    )
                )
        return True

    def _extract_handled_type(self, decorator: cst.Decorator) -> str | None:
        # Match @handle_errors(SomeException)
        dec = decorator.decorator
        if isinstance(dec, cst.Call) and isinstance(dec.func, cst.Name):
            if dec.func.value == "handle_errors" and dec.args:
                arg = dec.args[0].value
                if isinstance(arg, cst.Name):
                    return arg.value
        return None
```

## Extension Point 3: Full Integrations

For complete framework support, implement the `Integration` protocol. This gives you:

- CLI subcommands (`bubble myframework audit`)
- Framework-specific exception semantics
- Full audit integration

### The Protocol

```python
from bubble.integrations.base import Integration, Entrypoint, GlobalHandler
from bubble.integrations.models import IntegrationData
import typer

class MyIntegration(Integration):
    @property
    def name(self) -> str:
        """Name used for CLI subcommands."""
        return "myframework"

    @property
    def cli_app(self) -> typer.Typer:
        """Typer app with CLI subcommands."""
        ...

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        """Find framework-specific entrypoints."""
        ...

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Find framework-specific global handlers."""
        ...

    def get_exception_response(self, exception_type: str) -> str | None:
        """Map exceptions to HTTP responses (for HTTP frameworks)."""
        ...

    def extract_integration_data(self, source: str, file_path: str) -> IntegrationData:
        """Extract all integration-specific data."""
        return IntegrationData(
            entrypoints=self.detect_entrypoints(source, file_path),
            global_handlers=self.detect_global_handlers(source, file_path),
        )
```

### Example: Django REST Framework Integration

```python
import typer
from bubble.integrations.base import Integration, Entrypoint, GlobalHandler
from bubble.integrations.models import IntegrationData
from bubble.enums import EntrypointKind


EXCEPTION_RESPONSES = {
    "rest_framework.exceptions.APIException": "HTTP {code}",
    "rest_framework.exceptions.NotFound": "HTTP 404",
    "rest_framework.exceptions.PermissionDenied": "HTTP 403",
    "rest_framework.exceptions.ValidationError": "HTTP 400",
}


class DRFIntegration(Integration):
    @property
    def name(self) -> str:
        return "drf"

    @property
    def cli_app(self) -> typer.Typer:
        app = typer.Typer(help="Django REST Framework commands")

        @app.command()
        def audit(directory: Path = typer.Option(".", "-d")):
            """Check DRF views for escaping exceptions."""
            # Implementation using shared audit logic
            ...

        @app.command()
        def entrypoints(directory: Path = typer.Option(".", "-d")):
            """List DRF API views."""
            ...

        return app

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        # Detect:
        # - Classes inheriting from APIView, ViewSet, GenericAPIView
        # - Functions decorated with @api_view
        ...

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        # Detect:
        # - EXCEPTION_HANDLER setting in settings.py
        # - Custom exception handler functions
        ...

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

### Registering Integrations

Integrations are registered in `bubble/integrations/__init__.py`:

```python
INTEGRATIONS: list[Integration] = [
    FlaskIntegration(),
    FastAPIIntegration(),
    CLIScriptsIntegration(),
    # Add yours here
]
```

For local development, you can also place integrations in `.flow/integrations/`.

## Working with LibCST

Bubble uses LibCST for AST parsing. Key patterns:

### Walking the AST

```python
import libcst as cst

class MyVisitor(cst.CSTVisitor):
    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        print(f"Found function: {node.name.value}")
        return True  # Continue visiting children

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        print(f"Found class: {node.name.value}")
        return True

module = cst.parse_module(source)
visitor = MyVisitor()
module.walk(visitor)
```

### Getting Line Numbers

```python
import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

class MyVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        pos = self.get_metadata(PositionProvider, node)
        print(f"Function at line {pos.start.line}")
        return True

wrapper = MetadataWrapper(cst.parse_module(source))
visitor = MyVisitor()
wrapper.walk(visitor)
```

### Checking Decorators

```python
def has_decorator(node: cst.FunctionDef, name: str) -> bool:
    for decorator in node.decorators:
        dec = decorator.decorator
        # @name
        if isinstance(dec, cst.Name) and dec.value == name:
            return True
        # @name(...)
        if isinstance(dec, cst.Call):
            if isinstance(dec.func, cst.Name) and dec.func.value == name:
                return True
            # @obj.name(...)
            if isinstance(dec.func, cst.Attribute) and dec.func.attr.value == name:
                return True
    return False
```

### Checking Base Classes

```python
def inherits_from(node: cst.ClassDef, base_name: str) -> bool:
    for base in node.bases:
        if isinstance(base.value, cst.Name) and base.value.value == base_name:
            return True
        if isinstance(base.value, cst.Attribute):
            if base.value.attr.value == base_name:
                return True
    return False
```

## Testing Your Extension

Create a fixture directory and test file:

```
tests/
├── fixtures/
│   └── celery_app/
│       └── tasks.py
└── test_celery.py
```

```python
# tests/fixtures/celery_app/tasks.py
from celery import Celery

app = Celery()

@app.task
def process_order(order_id: int) -> None:
    if not order_id:
        raise ValueError("Invalid order ID")
    # ...
```

```python
# tests/test_celery.py
from bubble.extractor import extract_from_directory
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

def test_celery_tasks_detected():
    model = extract_from_directory(FIXTURES / "celery_app", use_cache=False)

    celery_entrypoints = [
        e for e in model.entrypoints
        if e.metadata.get("framework") == "celery"
    ]

    assert len(celery_entrypoints) == 1
    assert celery_entrypoints[0].function == "process_order"
```

## Using AI Agents to Build Extensions

Bubble is designed to be extended with AI coding agents. Give your agent this prompt:

```
Read the following files to understand how bubble detects entrypoints:
- bubble/protocols.py (the interface)
- bubble/integrations/base.py (data structures)
- bubble/integrations/flask/detector.py (example implementation)

Then implement a detector for [YOUR FRAMEWORK] that finds:
- [List specific patterns to detect]

Put the implementation in .flow/detectors/[framework].py
```

The protocol is intentionally simple so LLMs can implement it without extensive context.

## Summary

| I want to... | Implement | Put it in |
|--------------|-----------|-----------|
| Detect custom entrypoints | `EntrypointDetector` | `.flow/detectors/` |
| Detect custom handlers | `GlobalHandlerDetector` | `.flow/detectors/` |
| Full framework support | `Integration` | `bubble/integrations/` or `.flow/integrations/` |

Start with detectors for quick wins. Graduate to full integrations when you need CLI commands and framework semantics.
