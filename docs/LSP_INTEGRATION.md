# Flow LSP Integration: Design Document

This document explores how Flow's static exception analysis could power IDE features through the Language Server Protocol (LSP). The goal is to surface exception flow information directly in the editor where developers make decisions.

## Vision

Imagine hovering over a function call and seeing:

```
requests.get(url)
─────────────────────────────────────
Can raise:
  • ConnectionError (network unreachable)
  • Timeout (request took too long)
  • HTTPError (4xx/5xx response)

Currently uncaught in this scope
```

Or seeing inline hints on Flask routes:

```python
@app.route("/users/<id>")
def get_user(id):  # ⚠️ ValidationError, KeyError can escape
    user = db.get_user(validate_id(id))
    return jsonify(user)
```

## Use Cases

### 1. Hover on Function Calls

When hovering over any function call, show what exceptions it can raise.

**Before:** Developer has no idea what `process_payment()` might throw
**After:** Hover shows `PaymentDeclined`, `NetworkError`, `ValidationError`

```
┌─────────────────────────────────────────────────┐
│ process_payment(amount, card)                   │
├─────────────────────────────────────────────────┤
│ Can raise:                                      │
│   PaymentDeclined   (flow/payments.py:45)       │
│   NetworkError      (via stripe.charge)         │
│   ValidationError   (flow/validation.py:23)     │
│                                                 │
│ Confidence: high (all calls resolved)           │
└─────────────────────────────────────────────────┘
```

### 2. Hover on Except Blocks

Show what the except block catches vs. what escapes.

```python
try:
    result = risky_operation()
except ValueError:  # Hover here
    handle_error()
```

Hover shows:

```
┌─────────────────────────────────────────────────┐
│ except ValueError                               │
├─────────────────────────────────────────────────┤
│ Catches:                                        │
│   ValueError        (flow/parser.py:12)         │
│   InvalidFormat     (subclass, data.py:8)       │
│                                                 │
│ Still escapes from try block:                   │
│   KeyError          (flow/lookup.py:34)         │
│   ConnectionError   (via requests.get)          │
└─────────────────────────────────────────────────┘
```

### 3. Inline Hints on Route Handlers

For Flask/FastAPI routes, show warnings when exceptions can escape.

```python
@app.route("/api/users", methods=["POST"])
def create_user():  # ⚠️ 2 uncaught exceptions
    data = request.get_json()
    validate_user(data)  # ValidationError
    return save_user(data)  # DatabaseError
```

Clicking the hint opens a panel with details:

```
Uncaught exceptions in create_user:

1. ValidationError (flow/validation.py:15)
   Call path: create_user → validate_user → check_email

2. DatabaseError (flow/db.py:89)
   Call path: create_user → save_user → db.insert

These will result in HTTP 500 responses.
```

### 4. Diagnostics (Squiggly Lines)

Optional diagnostics that highlight potential issues:

- **Warning:** Function call can raise exception not caught in scope
- **Info:** Exception caught by global handler (not a problem, just informational)
- **Hint:** Consider adding explicit handling for `X`

```python
def process_order(order_id):
    order = get_order(order_id)  # ⚠️ Warning: OrderNotFound not caught
    charge_card(order.payment)   # ⚠️ Warning: PaymentError not caught
    send_confirmation(order)     # ℹ️ Info: EmailError caught by global handler
```

### 5. Code Actions

Quick fixes and refactorings:

- **Add try/except:** Wrap call in try/except with suggested exception types
- **Add global handler:** Create error handler for this exception type
- **Propagate:** Add exception to function's docstring (for libraries)

```python
# Before: cursor on risky_call()
result = risky_call()

# Code action: "Wrap in try/except for NetworkError"
# After:
try:
    result = risky_call()
except NetworkError:
    # TODO: Handle NetworkError
    raise
```

### 6. Go to Definition for Exceptions

Click on an exception type in hover/diagnostics to jump to where it's raised.

```
ValidationError → flow/validation.py:23
```

### 7. Workspace-Wide Exception Search

Command palette: "Flow: Find all routes that can raise X"

```
> Flow: Find routes that raise ValidationError

Results:
  POST /api/users     (create_user)
  PUT /api/users/:id  (update_user)
  POST /api/orders    (create_order)
```

## Architecture

### High-Level Design

```
┌──────────────────────────────────────────────────────────────┐
│                        VS Code / IDE                          │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                   Flow Extension                         │ │
│  │  - Registers hover provider                              │ │
│  │  - Registers diagnostics                                 │ │
│  │  - Handles commands (find routes, etc.)                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                              │                                │
│                         LSP Protocol                          │
│                              │                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                   Flow Language Server                   │ │
│  │  - Maintains ProgramModel in memory                      │ │
│  │  - Watches for file changes                              │ │
│  │  - Responds to hover/diagnostics requests                │ │
│  │  - Incremental updates on file save                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      Flow Core Library                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐ │
│  │ Extractor   │ │ Propagation │ │ Queries                 │ │
│  │ (libcst)    │ │ (fixpoint)  │ │ (escapes, raises, etc.) │ │
│  └─────────────┘ └─────────────┘ └─────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Server Lifecycle

1. **Startup:** Build full `ProgramModel` for workspace
2. **Ready:** Respond to hover/diagnostics requests from cached model
3. **File Change:** Incrementally update affected parts of model
4. **Shutdown:** Clean up resources

### Incremental Updates

Full model rebuild on every keystroke is too slow. Strategy:

1. **Per-file extraction:** Store extracted data per file
2. **Dependency tracking:** Know which files import which
3. **Lazy propagation:** Only recompute exception flow when queried

```python
class IncrementalModel:
    def __init__(self):
        self.file_data: dict[Path, FileExtraction] = {}
        self.propagation_cache: PropagationResult | None = None
        self.dirty_files: set[Path] = set()

    def on_file_change(self, path: Path, content: str):
        # Re-extract just this file
        self.file_data[path] = extract_file(path, content)
        self.dirty_files.add(path)
        # Invalidate propagation (will recompute lazily)
        self.propagation_cache = None

    def get_escapes(self, function: str) -> list[str]:
        if self.propagation_cache is None:
            # Rebuild propagation from cached file data
            model = self._merge_file_data()
            self.propagation_cache = propagate_exceptions(model)
        return compute_escapes(function, self.propagation_cache)
```

### Memory Considerations

For large codebases (100k+ LOC):

| Data | Estimated Size |
|------|---------------|
| AST per file | ~10KB per 1k LOC |
| ProgramModel | ~50MB for 100k LOC |
| Propagation cache | ~20MB |
| Total | ~100MB for 100k LOC |

This is acceptable for modern machines. For very large monorepos, consider:
- Lazy loading: Only parse files as they're opened
- Scope limiting: Only analyze directories with opened files
- Tiered caching: Keep hot data in memory, cold data on disk

## Implementation Challenges

### 1. Python's Dynamic Nature

Python allows runtime modification of exception hierarchies:

```python
# Can't statically know what this raises
getattr(module, exception_name)()
```

**Mitigation:**
- Use confidence levels (high/medium/low)
- Show "unknown" for truly dynamic code
- Allow user-provided stubs for dynamic patterns

### 2. External Libraries

We don't parse third-party code, so we don't know what `requests.get()` raises.

**Mitigation:**
- Exception stubs (already implemented in Flow)
- Community-contributed stub library
- Auto-generate stubs from documentation/type hints

### 3. Startup Time

Full model build takes ~1.5s per 1k LOC. A 50k LOC project = 75 seconds.

**Mitigation:**
- Background indexing with progress indicator
- Prioritize open files for immediate feedback
- Cache model to disk between sessions
- Show "indexing..." message during startup

```
┌────────────────────────────────────────┐
│ Flow: Indexing workspace...            │
│ ████████████░░░░░░░░░░░░  45%          │
│ 234 / 521 files                        │
│                                        │
│ Hover info available for open files    │
└────────────────────────────────────────┘
```

### 4. Keeping Model Fresh

Files change. Model must stay current.

**Mitigation:**
- File watcher for saves
- Debounce rapid changes (wait 500ms after last change)
- Incremental updates (reparse only changed file)
- Full rebuild on import changes (rare)

### 5. False Positives

Static analysis will have false positives. Users will get annoyed.

**Mitigation:**
- Confidence indicators (high/medium/low)
- "Strict mode" setting for fewer, higher-confidence results
- Easy suppression mechanism (`# flow: ignore`)
- Diagnostics off by default (opt-in)

## MVP Scope

For a first release, focus on maximum value with minimum complexity:

### MVP Features (v0.1)

1. **Hover on function calls** - Show exceptions that can escape
2. **Hover on except blocks** - Show what's caught vs. escaping
3. **Status bar indicator** - Show "Flow: Ready" / "Flow: Indexing..."
4. **Command: Find routes for exception** - Workspace search

### Not in MVP

- Inline hints (requires virtual text support)
- Diagnostics (too noisy without tuning)
- Code actions (complex UX)
- Incremental updates (full rebuild on save is fine for v0.1)

### MVP Technical Requirements

- Python LSP server using `pygls` library
- VS Code extension (TypeScript client)
- Disk cache for model (avoid re-indexing)
- Settings for enable/disable, stub paths

## Example VS Code Configuration

```json
{
  "flow.enable": true,
  "flow.stubPaths": [
    ".flow/stubs",
    "${workspaceFolder}/stubs"
  ],
  "flow.confidenceThreshold": "medium",
  "flow.showDiagnostics": false,
  "flow.indexOnStartup": true,
  "flow.excludePatterns": [
    "**/tests/**",
    "**/venv/**"
  ]
}
```

## Example Hover Response (LSP)

```typescript
// Request: textDocument/hover at position (10, 15)
// File content at that position: process_payment(amount)

// Response:
{
  "contents": {
    "kind": "markdown",
    "value": "### `process_payment(amount)`\n\n**Can raise:**\n- `PaymentDeclined` (payments.py:45)\n- `NetworkError` (via stripe.charge)\n- `ValidationError` (validation.py:23)\n\n**Confidence:** high\n\n*Currently uncaught in this scope*"
  },
  "range": {
    "start": { "line": 10, "character": 4 },
    "end": { "line": 10, "character": 30 }
  }
}
```

## Comparison with Existing Tools

| Tool | Exception Info | Route Analysis | Dynamic Python |
|------|---------------|----------------|----------------|
| Pyright | Partial (via types) | No | Limited |
| Pylint | Basic raise detection | No | No |
| mypy | No | No | No |
| **Flow LSP** | Full propagation | Yes | Stubs + heuristics |

Flow's unique value: **propagation through call chains** + **framework awareness**.

Pyright knows `raise ValueError` exists. Flow knows it propagates through 3 functions to reach an HTTP endpoint.

## Development Roadmap

### Phase 1: Foundation (2-3 weeks)
- [ ] Basic LSP server with `pygls`
- [ ] Hover provider for function calls
- [ ] VS Code extension scaffold
- [ ] Disk caching for model

### Phase 2: Core Features (2-3 weeks)
- [ ] Hover on except blocks
- [ ] Status bar integration
- [ ] Workspace search command
- [ ] Settings panel

### Phase 3: Polish (2-3 weeks)
- [ ] Incremental updates
- [ ] Performance optimization
- [ ] Error handling and edge cases
- [ ] Documentation and examples

### Phase 4: Advanced (future)
- [ ] Inline hints
- [ ] Diagnostics (opt-in)
- [ ] Code actions
- [ ] Multi-root workspace support
- [ ] Remote development support

## Open Questions

1. **Should diagnostics be on by default?** Probably not - too noisy initially. Let users opt in after they trust the tool.

2. **How to handle monorepos?** Could use `.flow/config.yaml` to define analysis boundaries.

3. **Should we support other editors?** LSP is editor-agnostic, but VS Code is the priority. Neovim and Sublime Text would be natural next targets.

4. **Integration with existing Python LSPs?** Could potentially be a Pylance/Pyright plugin rather than standalone server.

5. **How to fund stub development?** Community contributions? Paid tier for auto-generated stubs from documentation?

## Conclusion

An LSP integration would transform Flow from a CLI audit tool into an always-on development assistant. The key insight is that exception flow information is most valuable **at the moment of writing code**, not during periodic audits.

The MVP is achievable with a few weeks of focused work. The main risks are:
- Startup time for large codebases (mitigated by caching)
- False positive noise (mitigated by confidence levels and opt-in diagnostics)
- Maintenance burden (mitigated by building on existing Flow core)

If Flow proves useful in CLI form, LSP integration is a natural evolution.
