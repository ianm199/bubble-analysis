# Bubble

Static analysis tool for tracing exception flow through Python codebases.

**What can escape from my API endpoints?** Bubble answers this by parsing your code, building a call graph, and computing which exceptions propagate to each entrypoint.

## Quick Start

```bash
pip install bubble-analysis
```

```bash
# Check Flask routes for uncaught exceptions
bubble flask audit -d /path/to/project

# Check FastAPI routes
bubble fastapi audit -d /path/to/project

# Deep dive into one function
bubble escapes create_user -d /path/to/project

# Visualize the call tree
bubble trace create_user -d /path/to/project
```

## What It Does

Bubble finds your HTTP routes and CLI scripts, traces the call graph, and reports which exceptions can escape:

```
$ bubble flask audit

Scanning 23 flask entrypoints...

3 entrypoints have uncaught exceptions:

  POST /users/import
    └─ FileNotFoundError (importers.py:45)
    └─ ValidationError (validators.py:12)

  GET /reports/{id}
    └─ PermissionError (auth.py:89)

20 entrypoints fully covered by exception handlers
```

For a specific endpoint, see the full picture:

```
$ bubble escapes create_user

Exceptions that can escape from POST /users:

  FRAMEWORK-HANDLED (converted to HTTP response):
    HTTPException
      └─ becomes: HTTP 404
      └─ raised in: routes/users.py:45 (get_user) [high confidence]

  CAUGHT BY GLOBAL HANDLER:
    ValidationError (@errorhandler(AppError))
      └─ raised in: validators.py:27 (validate_input) [high confidence]

  UNCAUGHT (will propagate to caller):
    ConnectionError
      └─ raised in: db/client.py:45 (execute) [medium confidence]
      └─ call path: create_user → save_user → db.execute
```

Visualize as a tree:

```
$ bubble trace create_user

POST /users  → escapes: ValidationError, ConnectionError
├── validate_input()  → ValidationError
│   └── raises ValidationError (validators.py:27)
└── save_user()  → ConnectionError
    └── db.execute()  → ConnectionError
        └── raises ConnectionError (db/client.py:45)
```

## Features

- **Extensible**: Adapt to any framework or custom pattern ([see extending guide](docs/EXTENDING.md))
- **Entrypoint detection**: Flask routes, FastAPI routes, CLI scripts (`if __name__ == "__main__"`)
- **Global handler awareness**: Understands `@errorhandler`, `add_exception_handler`
- **Exception hierarchy**: Knows that catching `AppError` also catches `ValidationError` if it's a subclass
- **Polymorphism**: Expands abstract method calls to all concrete implementations
- **Framework-handled exceptions**: Detects HTTPException, ValidationError → HTTP responses
- **Confidence levels**: Shows high/medium/low confidence based on resolution quality
- **Resolution modes**: `--strict` for precision, `--aggressive` for recall
- **Exception stubs**: Built-in stubs for requests, sqlalchemy, httpx, redis, boto3
- **JSON output**: All commands support `-f json` for CI/automation
- **Caching**: SQLite-based caching for fast repeated analysis
- **Python 3.10+**: Supports Python 3.10, 3.11, 3.12, and 3.13

## Commands

### Core Commands (framework-agnostic)

| Command | Description |
|---------|-------------|
| `bubble raises <exception>` | Find all places an exception is raised |
| `bubble escapes <function>` | Show what can escape from a specific function |
| `bubble callers <function>` | Find all callers of a function |
| `bubble catches <exception>` | Find all places an exception is caught |
| `bubble trace <function>` | Visualize exception flow as a call tree |
| `bubble exceptions` | Show the exception class hierarchy |
| `bubble subclasses <class>` | Show class inheritance tree |
| `bubble stubs <action>` | Manage exception stubs (`list`, `init`, `validate`) |
| `bubble stats` | Show codebase statistics |

### Framework-Specific Commands

| Command | Description |
|---------|-------------|
| `bubble flask audit` | Check Flask routes for escaping exceptions |
| `bubble flask entrypoints` | List Flask HTTP routes |
| `bubble flask routes-to <exc>` | Which Flask routes can trigger this exception? |
| `bubble fastapi audit` | Check FastAPI routes for escaping exceptions |
| `bubble fastapi entrypoints` | List FastAPI HTTP routes |
| `bubble fastapi routes-to <exc>` | Which FastAPI routes can trigger this exception? |
| `bubble cli audit` | Check CLI scripts for escaping exceptions |
| `bubble cli entrypoints` | List CLI scripts |
| `bubble cli scripts-to <exc>` | Which CLI scripts can trigger this exception? |

All commands accept:
- `-d, --directory`: Directory to analyze (default: current)
- `-f, --format`: Output format (`text` or `json`)
- `--no-cache`: Disable caching

The `escapes` command accepts additional flags:
- `--strict`: High precision mode - only includes precisely resolved calls
- `--aggressive`: High recall mode - includes fuzzy matches

## Supported Frameworks

**Detected automatically:**
- Flask (`@app.route`, `@blueprint.route`, `@app.errorhandler`)
- FastAPI (`@router.get/post/put/delete`, `add_exception_handler`)
- CLI scripts (`if __name__ == "__main__"`)

**Not yet supported:**
- Django
- Celery tasks
- Scheduled jobs (APScheduler, etc.)

Custom patterns can be added via `.flow/detectors/`.

## Extending Bubble

> **Bubble is designed to be adapted to your codebase.** The core engine handles exception propagation—you just tell it where your entrypoints are.

Every codebase has its own patterns: internal RPC frameworks, custom decorators, queue handlers, scheduled jobs. Bubble's extension system lets you teach it your patterns without modifying the core.

**Full guide: [docs/EXTENDING.md](docs/EXTENDING.md)**

### What You Can Extend

| Pattern | Example | How to add |
|---------|---------|------------|
| Custom entrypoints | Celery tasks, Django views, gRPC handlers | `EntrypointDetector` |
| Custom error handlers | Middleware, decorators | `GlobalHandlerDetector` |
| Full framework | Django REST Framework, Airflow | `Integration` protocol |

### Quick Example

Drop a detector in `.flow/detectors/` and bubble auto-loads it:

```python
# .flow/detectors/celery.py
from bubble.protocols import EntrypointDetector
from bubble.integrations.base import Entrypoint
from bubble.enums import EntrypointKind

class CeleryTaskDetector(EntrypointDetector):
    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        # Find @app.task decorators, return Entrypoint objects
        ...
```

### AI-Friendly Design

The protocol is intentionally simple for LLMs. Give your agent:

```
Read bubble/protocols.py and bubble/integrations/flask/detector.py.
Implement a detector for [YOUR FRAMEWORK] that finds [PATTERNS].
Put it in .flow/detectors/[framework].py
```

See **[docs/EXTENDING.md](docs/EXTENDING.md)** for complete examples including Celery, Django REST Framework, and custom decorator patterns.

## Configuration

Bubble can be configured via `.flow/config.yaml`:

```yaml
resolution_mode: default  # "strict", "default", or "aggressive"
exclude:
  - vendor
  - migrations
```

### Exception Stubs

Bubble includes built-in stubs for common libraries (requests, sqlalchemy, httpx, redis, boto3). These declare what exceptions external library functions can raise.

Add custom stubs in `.flow/stubs/`:

```yaml
# .flow/stubs/mylib.yaml
module: mylib

functions:
  do_thing:
    - MyLibError
    - TimeoutError
```

Manage stubs with `bubble stubs list` and `bubble stubs validate`.

## How It Works

1. **Parse**: LibCST parses all Python files
2. **Extract**: Find functions, classes, raise/catch sites, calls, entrypoints
3. **Build call graph**: Track who calls whom, resolve method calls
4. **Propagate**: Fixed-point iteration computes which exceptions escape each function
5. **Report**: For each entrypoint, show caught vs uncaught exceptions

## Limitations

- **Over-approximation**: May report more exceptions than actually possible (e.g., all implementations of an abstract method)
- **Under-approximation**: Dynamic dispatch, `eval()`, and external libraries can't be fully traced
- **No runtime info**: Analysis is purely static

## Development

```bash
git clone https://github.com/ianm199/bubble-analysis
cd bubble-analysis
uv pip install -e ".[dev]"
uv run pytest
```

## License

MIT
