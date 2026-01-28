# flow

Static analysis tool for tracing exception flow through Python codebases.

**What can escape from my API endpoints?** Flow answers this by parsing your code, building a call graph, and computing which exceptions propagate to each entrypoint.

## Quick Start

```bash
pip install flow-analysis
```

```bash
# Check all endpoints for uncaught exceptions
flow audit -d /path/to/project

# Deep dive into one endpoint
flow escapes create_user -d /path/to/project

# Visualize the call tree
flow trace create_user -d /path/to/project
```

## What It Does

Flow finds your HTTP routes and CLI scripts, traces the call graph, and reports which exceptions can escape:

```
$ flow audit

Scanning 23 entrypoints...

✗ 3 entrypoints have uncaught exceptions:

  POST /users/import
    └─ FileNotFoundError (importers.py:45)
    └─ ValidationError (validators.py:12)

  GET /reports/{id}
    └─ PermissionError (auth.py:89)

✓ 20 entrypoints fully covered by exception handlers
```

For a specific endpoint, see the full picture:

```
$ flow escapes create_user

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
$ flow trace create_user

POST /users  → escapes: ValidationError, ConnectionError
├── validate_input()  → ValidationError
│   └── raises ValidationError (validators.py:27)
└── save_user()  → ConnectionError
    └── db.execute()  → ConnectionError
        └── raises ConnectionError (db/client.py:45)
```

## Features

- **Entrypoint detection**: Flask routes, FastAPI routes, CLI scripts (`if __name__ == "__main__"`)
- **Global handler awareness**: Understands `@errorhandler`, `add_exception_handler`
- **Exception hierarchy**: Knows that catching `AppError` also catches `ValidationError` if it's a subclass
- **Polymorphism**: Expands abstract method calls to all concrete implementations
- **Framework-handled exceptions**: Detects HTTPException, ValidationError → HTTP responses
- **Confidence levels**: Shows high/medium/low confidence based on resolution quality
- **Resolution modes**: `--strict` for precision, `--aggressive` for recall
- **Exception stubs**: Declare what external libraries can raise (requests, sqlalchemy, etc.)
- **JSON output**: All commands support `-f json` for CI/automation
- **Caching**: SQLite-based caching for fast repeated analysis

## Commands

| Command | Description |
|---------|-------------|
| `flow audit` | Check all entrypoints for escaping exceptions |
| `flow escapes <function>` | Show what can escape from a specific function |
| `flow trace <function>` | Visualize exception flow as a call tree |
| `flow entrypoints` | List all HTTP routes and CLI scripts |
| `flow raises <exception>` | Find all places an exception is raised |
| `flow catches <exception>` | Find all places an exception is caught |
| `flow exceptions` | Show the exception class hierarchy |
| `flow callers <function>` | Find all callers of a function |
| `flow subclasses <class>` | Show class inheritance tree |
| `flow stubs <action>` | Manage exception stubs (`list`, `init`, `validate`) |
| `flow stats` | Show codebase statistics |

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

Custom patterns can be added via `.flow/detectors/` (run `flow init` to set up).

## Configuration

Flow can be configured via `.flow/config.yaml`:

```yaml
resolution_mode: default  # "strict", "default", or "aggressive"
exclude:
  - vendor
  - migrations
```

### Exception Stubs

Flow includes built-in stubs for common libraries (requests, sqlalchemy, httpx, redis, boto3). These declare what exceptions external library functions can raise.

Add custom stubs in `.flow/stubs/`:

```yaml
# .flow/stubs/mylib.yaml
mylib:
  do_thing:
    - MyLibError
    - TimeoutError
```

Manage stubs with `flow stubs list` and `flow stubs validate`.

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
git clone https://github.com/yourusername/flow-analysis
cd flow-analysis
pip install -e ".[dev]"
pytest
```

## License

MIT
