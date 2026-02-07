# Bubble for Zed

See exception flow through your Python codebase directly in Zed.

## What it does

**Route diagnostics** — warning squiggly lines appear on route decorators (`@router.get(...)`, `@app.route(...)`) where uncaught exceptions can escape. The warning message shows the route path and exception types.

**Hover** — context-sensitive exception info based on cursor position:

- **`def` lines**: Shows all exceptions that can escape from the function (uncaught, framework-handled, caught locally, caught by global handler)
- **Function calls**: Shows what exceptions the callee can throw
- **Everything else**: No popup (no noise)

## Suppressing warnings

Add a comment to dismiss diagnostics on specific routes:

```python
# Suppress all warnings on this route
@router.post("/users")  # bubble: ignore
def create_user():
    ...

# Suppress only specific exception types
@router.get("/items/{id}")  # bubble: ignore[ValueError, KeyError]
def get_item(item_id):
    ...
```

The comment can go on the decorator line, the def line, or any decorator in between.

## Requirements

Install [bubble-analysis](https://pypi.org/project/bubble-analysis/) with LSP support in your project's Python environment:

```bash
pip install bubble-analysis[lsp]
```

The extension finds `python3` on your PATH and runs `python -m bubble.lsp`.

## Configuration

Override the Python binary or arguments in your Zed settings (`settings.json`):

```json
{
  "lsp": {
    "bubble-lsp": {
      "binary": {
        "path": "/path/to/your/venv/bin/python",
        "arguments": ["-m", "bubble.lsp"]
      }
    }
  }
}
```

## How it works

The extension spawns a Python LSP server that:

1. Builds a program model of your codebase when you open a file
2. Propagates exceptions through the call graph (cached after first run)
3. Publishes diagnostics on route decorators with uncaught exceptions
4. Returns context-sensitive hover info based on cursor position

The model rebuilds automatically when you save a file.

## Supported frameworks

Exception flow analysis supports Flask, FastAPI, Django/DRF, and CLI scripts. Framework-specific exceptions (like `HTTPException`) are recognized and categorized appropriately.
