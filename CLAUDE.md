# Flow Analysis Tool

A Python static analysis tool that traces exception flow through codebases. Answers questions like "what HTTP endpoints can trigger this exception?"

## Mental Model

The tool builds a **program model** from Python source, then queries it:

```
Source Files → Extraction (libcst) → Program Model → Queries → Results
```

The program model contains:
- **Functions/Classes**: All definitions with file, line, qualified names
- **Raise sites**: Where exceptions are thrown
- **Catch sites**: Where exceptions are caught (try/except)
- **Call sites**: Every function/method call with caller→callee relationship
- **Entrypoints**: HTTP routes (Flask/FastAPI) where execution begins
- **Import maps**: Per-file mapping of local names to their source modules

## Call Resolution Strategy

Python is dynamic, so perfect static resolution is impossible. We use **layered resolution** with fallback:

| Layer | Resolves | Example |
|-------|----------|---------|
| Import resolution | Direct calls | `from X import foo` → `foo()` resolves to `X.foo` |
| Self-method | `self.method()` | Inside `class Foo`, resolves to `Foo.method` |
| Constructor tracking | `x = Foo(); x.bar()` | Tracks assignment, resolves to `Foo.bar` |
| Name-based fallback | Everything else | Match by bare function name |

The fallback works surprisingly well because function names are usually unique within a project.

### Key Implementation Detail

When tracing, callers are stored as qualified names like `file.py::Class::method`. When looking up who calls a function:
1. Try exact match in qualified graph
2. Extract simple name (`method`) and try name graph

The extraction step is critical - without it, qualified names fail to match bare-name keys.

## Case Study: Factory Pattern

Consider a codebase with a factory pattern that exercises all resolution layers:

```
POST /balance (route handler)
    ↓
BalanceOrchestrator(request)              ← import resolution
    ↓
orchestrator.run()                        ← constructor tracking
    ↓
executor_factory(partner)                 ← import resolution
    ↓ returns ExecutorService
executor.process_request()                ← return type resolution
    ↓
self.transfer_funds()                     ← self-method resolution
    ↓
raise ServiceException(...)               ← traced back to POST /balance
```

This pattern informed the layered design. Each layer handles one hop in the chain.

## Code Organization

```
flow/
├── models.py       # Core data structures (CallSite, RaiseSite, etc.)
├── extractor.py    # libcst visitors that build the program model
├── propagation.py  # Exception flow computation (fixpoint iteration)
├── results.py      # Typed dataclasses for query results (the contract)
├── queries.py      # Core query functions (raises, callers, escapes, etc.)
├── formatters.py   # Core output rendering (text and JSON)
├── config.py       # Configuration loading (.flow/config.yaml)
├── stubs.py        # Exception stub loading for external libraries
├── stubs/          # Built-in YAML stubs (requests, sqlalchemy, etc.)
├── cache.py        # SQLite-based caching
├── cli.py          # Core CLI + integration subcommand registration
│
└── integrations/   # Framework-specific code (Flask, FastAPI, CLI scripts)
    ├── __init__.py     # Integration registry and discovery
    ├── base.py         # Entrypoint, GlobalHandler, Integration protocol
    ├── models.py       # AuditResult, EntrypointsResult, etc.
    ├── queries.py      # Shared audit/entrypoint logic for integrations
    ├── formatters.py   # Shared integration formatters
    │
    ├── flask/          # Flask integration
    │   ├── detector.py     # FlaskRouteVisitor, FlaskErrorHandlerVisitor
    │   ├── semantics.py    # EXCEPTION_RESPONSES (HTTPException mappings)
    │   └── cli.py          # `flow flask` subcommands
    │
    ├── fastapi/        # FastAPI integration
    │   ├── detector.py     # FastAPIRouteVisitor, FastAPIExceptionHandlerVisitor
    │   ├── semantics.py    # EXCEPTION_RESPONSES
    │   └── cli.py          # `flow fastapi` subcommands
    │
    └── cli_scripts/    # CLI script integration
        ├── detector.py     # CLIEntrypointVisitor
        └── cli.py          # `flow cli` subcommands
```

### Architecture: Clean Separation of Concerns

The CLI follows a strict layered architecture:

```
cli.py (args) → queries.py (logic) → formatters.py (output)
                    ↓
              results.py (typed contracts)
```

Each command is ~5 lines:
```python
@app.command()
def raises(exception_type, directory, include_subclasses, output_format, no_cache):
    directory = directory.resolve()
    model = build_model(directory, use_cache=not no_cache)
    result = queries.find_raises(model, exception_type, include_subclasses)
    formatters.raises(result, output_format, directory, console)
```

### models.py

Dataclasses for the program model. Key fields on `CallSite`:
- `caller_qualified`: Always populated (`file.py::Class::func`)
- `callee_qualified`: Populated when resolved, else None
- `callee_name`: Always populated (bare name for fallback)
- `resolution_kind`: How it was resolved ("import", "self", "constructor", "return_type", "name_fallback", "polymorphic", "stub", "unresolved")

Trust-related data structures:
- `ResolutionEdge`: Records a call resolution with metadata (caller, callee, resolution_kind, is_heuristic)
- `ExceptionEvidence`: Combines raise site, call path, and confidence level
- `compute_confidence()`: Derives high/medium/low from resolution kinds in a path

### extractor.py

`CodeExtractor` is a libcst visitor that walks the AST once, collecting:
- Function/class definitions (with return type annotations)
- Import statements (building the import map)
- Raise/try-except statements
- Call expressions (resolving where possible)
- Assignments (for constructor tracking)

The visitor maintains stacks for current class/function context.

### propagation.py

Exception flow computation using fixpoint iteration:
- `build_forward_call_graph()`: Map from caller to callees
- `build_reverse_call_graph()`: Map from callee to callers (qualified + name-based)
- `compute_direct_raises()`: Exceptions raised directly in each function
- `propagate_exceptions()`: Fixpoint iteration to propagate through call graph (accepts `resolution_mode` and `stub_library` params)
- `compute_exception_flow()`: Categorize exceptions as caught locally, or uncaught (framework-specific categorization is in integrations/)
- `compute_reachable_functions()`: Find all functions reachable from a given function

Trust features:
- `PropagatedRaise`: Tracks exceptions with their full call path through propagation
- Resolution mode filtering: strict (high precision), default, aggressive (high recall)
- Stub integration: External library exceptions injected via `StubLibrary`

Framework-specific exception handling (HTTPException → HTTP response) is now in `integrations/queries.py`.

### results.py

Typed dataclasses defining the contract between queries and formatters:
- `RaisesResult`, `CallersResult`, `StatsResult`, etc.
- Each query returns one of these; each formatter consumes one
- Enables testing queries without CLI, and swapping formatters

### queries.py

Core query logic lives here. Each function takes a `ProgramModel` and returns a typed result:
- `find_raises()` → `RaisesResult`
- `find_callers()` → `CallersResult`
- `find_escapes()` → `EscapesResult`
- `trace_function()` → `TraceResult`

Helper functions (prefixed with `_`) handle graph traversal, name matching, etc.

Integration-specific queries (audit, entrypoints, routes-to) live in `integrations/queries.py`.

### formatters.py

Core output rendering (text and JSON). One function per result type:
- `raises(result, output_format, directory, console)`
- `callers(result, output_format, directory, console, show_resolution)`
- `escapes(result, output_format, directory, console)`

Integration-specific formatters live in `integrations/formatters.py`.

No business logic in formatters - just formatting decisions.

### integrations/

Framework-specific code is isolated in the `integrations/` directory:
- **base.py**: Defines `Entrypoint`, `GlobalHandler`, and `Integration` protocol
- **models.py**: `AuditResult`, `EntrypointsResult`, `RoutesToResult`
- **queries.py**: Shared `audit_integration()`, `list_integration_entrypoints()`, `trace_routes_to_exception()`
- **formatters.py**: Shared formatting for integration results

Each framework (flask/, fastapi/, cli_scripts/) has:
- **detector.py**: AST visitors to detect routes/handlers
- **semantics.py**: Exception-to-HTTP-response mappings
- **cli.py**: Subcommands registered under `flow <framework>`

### cli.py

Thin layer (~300 lines) that only does:
1. Argument parsing via typer decorators
2. Call `build_model()` to get the program model
3. Call `queries.xyz()` to run the query
4. Call `formatters.xyz()` to render output

## Commands

### Core Commands (framework-agnostic)

```bash
flow raises <Exception> [-s]      # Find where exception is raised (-s includes subclasses)
flow escapes <function>           # What exceptions can escape from this function?
flow escapes <function> --strict  # High precision mode (only resolved calls)
flow callers <function> [-r]      # Who calls this function? (-r shows resolution kind)
flow catches <Exception>          # Where is this exception caught?
flow trace <function>             # Visualize exception flow as a call tree
flow exceptions                    # Show exception class hierarchy
flow stubs list                    # Show loaded exception stubs
flow stubs validate                # Validate stub YAML files
flow stats                         # Codebase statistics
```

### Framework-Specific Commands (namespaced)

```bash
# Flask
flow flask audit                  # Check Flask routes for escaping exceptions
flow flask entrypoints            # List Flask HTTP routes
flow flask routes-to <Exception>  # Which Flask routes can trigger this exception?

# FastAPI
flow fastapi audit                # Check FastAPI routes for escaping exceptions
flow fastapi entrypoints          # List FastAPI HTTP routes
flow fastapi routes-to <Exception># Which FastAPI routes can trigger this exception?

# CLI scripts (if __name__ == "__main__")
flow cli audit                    # Check CLI scripts for escaping exceptions
flow cli entrypoints              # List CLI scripts
flow cli scripts-to <Exception>   # Which CLI scripts can trigger this exception?
```

**Typical workflow:**
```bash
flow flask audit              # Find which routes have uncaught exceptions
flow escapes <function>       # Investigate a specific one
flow trace <function>         # Visualize the call tree
```

## Gotchas

**Rich markup**: `[text]` is interpreted as markup. Escape with `\[text]` or it disappears.

**visit_Raise must return True**: Otherwise child nodes (like the Call inside `raise Foo()`) aren't visited.

**Qualified vs simple name lookup**: When falling back to name_graph, extract the simple name first. A qualified name like `file.py::Class::method` won't match the bare key `method`.

## Future Work

**Near-term:**
- `--entrypoint` filter for raises - scope to specific endpoint
- `flow exception-map <endpoint>` - inverse of entrypoints-to
- Exception-specific stats - raises/catches/entrypoints for one type
- Distinguish dead code vs test/CLI/background job callers

**Long-term:**
- Pyright integration for type-aware resolution

**Completed:**
- External library exception stubs (declare what `requests.get()` can raise) - see `flow stubs`
- Confidence tiers for heuristic vs precise resolution - see `--strict` flag and confidence labels
- Framework-handled exceptions (HTTPException → HTTP response) - auto-detected for Flask/FastAPI
- Separation of core and integrations - framework-specific code in `flow/integrations/`

## Code Style

### No Inline Comments

Anything important belongs in a docstring, not scattered through code.

### No Fallback Patterns

Use a single source of truth. If data might be missing, that's a bug to fix upstream.

```python
# Bad - papering over data issues
name = item.get("name") or item.get("title") or "Unknown"

# Good - single source, fail explicitly
name = item["name"]
```

### Type Hints Required

All public functions need type hints. Pyright strict mode is enabled.

## Development

### Running Checks

```bash
ruff check flow/ --fix        # Lint and auto-fix
ruff format flow/             # Format
pyright                       # Type check (strict mode)
semgrep --config .semgrep/    # Project-specific rules
```

### What the Tools Enforce

| Tool | What it checks |
|------|----------------|
| `ruff` | Import sorting, unused imports, modern Python syntax, formatting |
| `pyright` | Type safety (strict mode) |
| `semgrep` | Magic strings, layer boundaries, import violations |

### Semgrep Rules (`.semgrep/`)

These are project-specific rules beyond what ruff checks:

- **magic-strings.yaml** - Catches `status == "pending"` patterns. Use typed enums instead.
- **layer-boundaries.yaml** - Catches `db.query()` in route files. Move to services.
- **import-violations.yaml** - Catches utils importing business logic. Keeps utils pure.

### Pre-commit

Pre-commit hooks run ruff + semgrep on every commit. Install with:

```bash
uv pip install pre-commit
pre-commit install
```
