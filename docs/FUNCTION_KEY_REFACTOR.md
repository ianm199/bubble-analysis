# FunctionKey Refactor Spec

## Problem

Function identity is inconsistent across the codebase. There are two key formats:

| Where | Format | Example |
|-------|--------|---------|
| `model.functions` dict keys | Single colon | `services.py:ServiceA.process` |
| Everything else (call_sites, raise_sites, propagation, forward graph) | Double colon | `services.py::ServiceA.process` |

This mismatch is papered over with `endswith` fuzzy matching in three critical places:

```python
# propagation.py:828
for key in propagation.propagated_raises:
    if key.endswith(f"::{function_name}") or key.endswith(f".{function_name}"):

# integrations/queries.py:77
for key in propagation.propagated_raises:
    if key.endswith(f"::{function_name}") or key.endswith(f".{function_name}"):

# queries.py:466
for key in propagated_raises:
    if key.endswith(f"::{function_name}") or key.endswith(f".{function_name}"):
```

This breaks when a caller passes a **full key** (like the LSP does: `backend/agent/routes.py::start_sandbox_agent`), because the endswith check constructs `::backend/agent/routes.py::start_sandbox_agent` which never matches. The functions silently return empty results.

Additionally, `Entrypoint.function` stores bare names (`start_sandbox_agent`) while most internal structures use full keys. This forces every consumer to know which format to pass.

## Goal

One canonical format for function identity, used everywhere. All lookups become exact dict lookups. Resolution from bare names happens once at system boundaries (CLI input, LSP hover, entrypoint detection).

## Design

### FunctionKey Type

```python
from typing import NewType

FunctionKey = NewType("FunctionKey", str)
```

Always in format: `relative/path.py::QualifiedName`

Examples:
- `services.py::ServiceA.process` (method)
- `main.py::caller` (function)
- `api/routes.py::start_sandbox_agent` (function in subdirectory)

### Model-Level Reverse Index

Built once during model assembly in `extract_from_directory()`:

```python
@dataclass
class ProgramModel:
    functions: dict[FunctionKey, FunctionDef] = field(default_factory=dict)
    name_to_keys: dict[str, list[FunctionKey]] = field(default_factory=dict)
    # ... rest unchanged
```

`name_to_keys` maps bare names and qualified names to their full keys:

```python
name_to_keys = {
    "process":           ["services.py::ServiceA.process", "services.py::ServiceB.process"],
    "ServiceA.process":  ["services.py::ServiceA.process"],
    "caller":            ["main.py::caller"],
}
```

This makes resolution O(1) instead of a linear scan.

### Resolution at Boundaries

```python
class FunctionNotFoundError(Exception):
    """Raised when a function name cannot be resolved to a key."""
    def __init__(self, name: str, suggestions: list[str] | None = None) -> None:
        self.name = name
        self.suggestions = suggestions or []
        msg = f"Function not found: {name}"
        if self.suggestions:
            msg += f" (did you mean: {', '.join(self.suggestions)}?)"
        super().__init__(msg)


class AmbiguousFunctionError(Exception):
    """Raised when a function name matches multiple keys."""
    def __init__(self, name: str, matches: list[str]) -> None:
        self.name = name
        self.matches = matches
        super().__init__(f"Ambiguous function name '{name}' matches: {', '.join(matches)}")


def resolve_function_key(name: str, model: ProgramModel) -> FunctionKey:
    """Resolve a bare name, qualified name, or full key to a FunctionKey.

    Called at system boundaries: CLI input, LSP hover, entrypoint wiring.
    Raises FunctionNotFoundError or AmbiguousFunctionError.
    """
    # Already a full key
    if name in model.functions:
        return FunctionKey(name)

    # Look up by name
    matches = model.name_to_keys.get(name, [])
    if len(matches) == 1:
        return FunctionKey(matches[0])
    if len(matches) > 1:
        raise AmbiguousFunctionError(name, matches)

    # No match
    all_names = list(model.name_to_keys.keys())
    suggestions = get_close_matches(name, all_names, n=3, cutoff=0.5)
    raise FunctionNotFoundError(name, suggestions)
```

### What Changes

#### 1. `extractor.py` line 922 — Fix the single colon

```python
# Before
key = f"{path_str}:{func.qualified_name}"

# After
key = f"{path_str}::{func.qualified_name}"
```

Same fix for classes at line 926:

```python
# Before
key = f"{path_str}:{cls.qualified_name}"

# After
key = f"{path_str}::{cls.qualified_name}"
```

#### 2. `extractor.py` — Build `name_to_keys` during model assembly

In `extract_from_directory()`, after the aggregation loop, build the reverse index:

```python
name_to_keys: dict[str, list[str]] = {}
for key in model.functions:
    func = model.functions[key]
    # Map bare name -> key
    if func.name not in name_to_keys:
        name_to_keys[func.name] = []
    name_to_keys[func.name].append(key)
    # Map qualified name -> key (for methods like ServiceA.process)
    if func.qualified_name != func.name:
        if func.qualified_name not in name_to_keys:
            name_to_keys[func.qualified_name] = []
        name_to_keys[func.qualified_name].append(key)
model.name_to_keys = name_to_keys
```

#### 3. `models.py` — Add `name_to_keys` field and new exceptions

Add to `ProgramModel`:

```python
name_to_keys: dict[str, list[str]] = field(default_factory=dict)
```

Add `FunctionKey`, `FunctionNotFoundError`, `AmbiguousFunctionError`, and `resolve_function_key` to `models.py` (or a new `bubble/keys.py` if preferred, but models.py is the natural home since it holds `ProgramModel`).

#### 4. `propagation.py` — Delete fuzzy matching in `compute_exception_flow`

Lines 826-833 become:

```python
func_key = function_name  # Already a FunctionKey

if func_key not in propagation.propagated_raises:
    return flow
```

The entire endswith loop is deleted. The function signature changes from `function_name: str` to accept a `FunctionKey` (or just `str` since `NewType` is erased at runtime — but callers should resolve first).

#### 5. `integrations/queries.py` — Delete fuzzy matching in `_compute_exception_flow_for_integration`

Lines 75-82 become the same exact-match pattern. The caller (`audit_integration`) resolves entrypoint functions to full keys before passing them in.

#### 6. `queries.py` — Delete `find_function_key()` entirely

The function at lines 459-475 is replaced by `resolve_function_key()`. All callers switch to the new function.

Update `find_escapes()` (line 301-329):
- The `function_name` parameter is now resolved to a `FunctionKey` before being passed to `compute_forward_reachability` and `compute_exception_flow`.

Update `trace_function()` (line 619-658):
- Same pattern: resolve at the top, use exact keys throughout.

Update `audit_entrypoints()` (line 264-298):
- Resolve `entrypoint.function` to a `FunctionKey` before passing to `compute_exception_flow`.

#### 7. `propagation.py` — Delete `_build_func_name_index()`

Lines 74-87 exist only because `model.functions` uses single colon while everything else uses double colon. With consistent keys, this function is unnecessary. All callers that used it to bridge the format gap can do direct lookups instead.

#### 8. `integrations/base.py` — Entrypoint.function stays as bare name

`Entrypoint.function` continues to store bare names (e.g., `start_sandbox_agent`, `UserResource.post`). This is the right representation for detection — detectors see AST nodes and don't know file paths.

Resolution happens at the consumption boundary: when `audit_integration` or `_compute_exception_flow_for_integration` processes an entrypoint, it resolves `entrypoint.function` to a `FunctionKey` using `resolve_function_key()`.

#### 9. `bubble/lsp.py` — Resolve at the hover boundary

```python
function_key = f"{relative_file}::{func.qualified_name}"
# This is already a full key in the correct format, no resolution needed
# It can be passed directly to find_escapes()
```

The LSP was already constructing the right format. The fix is in `compute_exception_flow` accepting it.

## File-by-File Change List

| File | Change | Lines |
|------|--------|-------|
| `models.py` | Add `name_to_keys` field to `ProgramModel`. Add `FunctionKey` NewType, `FunctionNotFoundError`, `AmbiguousFunctionError`, `resolve_function_key()` | 356-371, new code |
| `extractor.py` | Fix `:` → `::` in function/class key construction. Build `name_to_keys` in `extract_from_directory()` | 922, 926, ~940 |
| `propagation.py` | Delete `_build_func_name_index()`. Replace endswith loop in `compute_exception_flow()` with exact lookup. Clean up `_normalize_callee_to_file_format()` which also handles both separators | 74-87, 826-833, 93-132 |
| `queries.py` | Delete `find_function_key()`. Update `find_escapes()`, `trace_function()`, `audit_entrypoints()` to resolve at boundary. Update `get_direct_raises_for_key()` to use exact lookup | 459-475, 301-329, 619-658, 264-298, 478-494 |
| `integrations/queries.py` | Replace endswith loop in `_compute_exception_flow_for_integration()` with exact lookup. Resolve entrypoint function names in `audit_integration()` | 75-82, 227-238 |
| `lsp.py` | No change needed — already constructs `path::name` format. Wrapping in try/except for `FunctionNotFoundError` is the only addition | 174 |
| `cache.py` | Cache keys will change format (`:` → `::`). Existing caches will auto-invalidate since keys won't match. No code change needed, but worth noting | N/A |

## Migration Notes

### Cache Invalidation

Changing the key format in `model.functions` means the SQLite cache (`.flow/cache.sqlite`) will produce models with the old single-colon format. Two options:

1. **Auto-invalidate**: Bump a cache version constant so old caches are ignored. Simplest.
2. **Do nothing**: The cache stores `FileExtraction` objects, not assembled models. The key is constructed in `extract_from_directory()` from `path_str` and `func.qualified_name` — so changing line 922 is sufficient. Old cached `FileExtraction` objects don't store keys, they store `FunctionDef` objects. **This means no cache migration is needed.**

Option 2 is correct — the cache stores raw extractions, not keyed models.

### Test Impact

Tests that construct `ProgramModel` directly with single-colon keys in `model.functions` will need updating. Search for patterns like `f"{path}:{name}"` in test files.

### Backward Compatibility

The CLI accepts bare function names (`bubble escapes start_sandbox_agent`). This continues to work because `resolve_function_key()` handles bare names via `name_to_keys`. The only difference is it now raises `FunctionNotFoundError` with suggestions instead of silently returning empty results.

## Ordering

1. Fix the colon (`extractor.py` line 922, 926)
2. Add `name_to_keys` field and build it (`models.py`, `extractor.py`)
3. Add `FunctionKey`, `resolve_function_key()`, error types (`models.py`)
4. Replace endswith loops with exact lookups (`propagation.py`, `integrations/queries.py`, `queries.py`)
5. Delete dead code (`_build_func_name_index`, `find_function_key`)
6. Update LSP error handling (`lsp.py`)
7. Update tests

Steps 1-3 can land together as they don't break anything (the old single-colon keys just become double-colon). Steps 4-5 are the behavioral change. Step 6-7 are follow-up.
