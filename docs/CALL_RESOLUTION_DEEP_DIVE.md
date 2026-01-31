# Call Resolution Deep Dive

This document explains Flow's call resolution system in detail, including the `name_fallback` mechanism and its implications for analysis accuracy. Intended for expert review.

## Executive Summary

Flow is a static analyzer that traces exception propagation through Python call graphs. The core challenge is **call resolution**: when we see `obj.method()`, we need to know which `method` to look up.

Python's dynamic typing makes perfect static resolution impossible. Flow uses a **layered resolution strategy** with fallback. The key question is whether the fallback mechanism (`name_fallback`) produces acceptable precision for real-world use.

## Data Model

### CallSite (models.py:97-108)

Every function call is recorded as a `CallSite`:

```python
@dataclass
class CallSite:
    """A location where a function is called."""

    file: str
    line: int
    caller_function: str
    callee_name: str                           # Always populated (bare name)
    is_method_call: bool
    caller_qualified: str | None = None        # e.g., "api/routes.py::UserController.create"
    callee_qualified: str | None = None        # Populated ONLY if resolution succeeded
    resolution_kind: ResolutionKind = "unresolved"
```

**Critical insight**: `callee_qualified` is `None` when resolution fails. The `callee_name` (bare name) is always available as fallback.

### ResolutionKind (models.py:85-94)

```python
ResolutionKind = Literal[
    "import",           # from X import foo; foo() → X.foo
    "self",             # self.method() → CurrentClass.method
    "constructor",      # x = Foo(); x.bar() → Foo.bar
    "return_type",      # def get() -> Foo; get().bar() → Foo.bar
    "name_fallback",    # Couldn't resolve, matched by bare name
    "polymorphic",      # Abstract method, multiple implementations
    "stub",             # From external stub file
    "unresolved",       # No resolution attempted/possible
]
```

### Confidence Scoring (models.py:132-138)

```python
def compute_confidence(edges: list[ResolutionEdge]) -> Literal["high", "medium", "low"]:
    """Compute confidence level based on resolution kinds in the path."""
    if any(e.resolution_kind in ("name_fallback", "polymorphic") for e in edges):
        return "low"
    if any(e.resolution_kind == "return_type" for e in edges):
        return "medium"
    return "high"
```

Any `name_fallback` in the call path → low confidence.

## Extraction Phase (extractor.py)

The `CodeExtractor` is a libcst visitor that walks the AST and builds `CallSite` objects.

### Call Resolution During Extraction (extractor.py:362-415)

```python
def visit_Call(self, node: cst.Call) -> bool:
    pos = self.get_metadata(PositionProvider, node)
    current_function = self._function_stack[-1] if self._function_stack else "<module>"

    caller_qualified = self._get_current_qualified_name()

    callee_name: str
    callee_qualified: str | None = None
    resolution_kind: str = "unresolved"
    is_method_call = False

    if isinstance(node.func, cst.Attribute):
        # Method call: obj.method()
        callee_name = node.func.attr.value
        is_method_call = True
        base_expr = node.func.value

        if isinstance(base_expr, cst.Name):
            base_name = base_expr.value
            if base_name == "self" and self._class_stack:
                # RESOLUTION: self.method() → CurrentClass.method
                callee_qualified = (
                    f"{self.relative_path}::{'.'.join(self._class_stack)}.{callee_name}"
                )
                resolution_kind = "self"
            elif base_name in self._local_types:
                # RESOLUTION: Known local variable type
                type_name = self._local_types[base_name]
                if type_name in self.import_map:
                    callee_qualified = f"{self.import_map[type_name]}.{callee_name}"
                    resolution_kind = "constructor"
                else:
                    callee_qualified = f"{self.relative_path}::{type_name}.{callee_name}"
                    resolution_kind = "constructor"

    elif isinstance(node.func, cst.Name):
        # Direct call: foo()
        callee_name = node.func.value
        if callee_name in self.import_map:
            # RESOLUTION: Imported name
            callee_qualified = self.import_map[callee_name]
            resolution_kind = "import"
    else:
        return True

    self.call_sites.append(
        CallSite(
            file=self.file_path,
            line=pos.start.line,
            caller_function=current_function,
            callee_name=callee_name,           # ALWAYS populated
            is_method_call=is_method_call,
            caller_qualified=caller_qualified,
            callee_qualified=callee_qualified,  # None if unresolved!
            resolution_kind=resolution_kind,
        )
    )

    return True
```

### What Gets Resolved vs. Unresolved

| Pattern | Resolution | Example |
|---------|------------|---------|
| `foo()` where `from X import foo` | `import` ✓ | `callee_qualified = "X.foo"` |
| `self.method()` inside class | `self` ✓ | `callee_qualified = "file.py::Class.method"` |
| `x = Foo(); x.bar()` | `constructor` ✓ | `callee_qualified = "file.py::Foo.bar"` |
| `obj.method()` unknown type | `unresolved` ✗ | `callee_qualified = None` |
| `result.process()` from function return | `unresolved` ✗ | `callee_qualified = None` |

**The gap**: Most method calls on parameters, return values, or dynamically-typed variables remain unresolved.

## Propagation Phase (propagation.py)

This is where `name_fallback` happens. The propagation algorithm computes which exceptions can escape from each function.

### Building the Call Graph (propagation.py:63-75)

```python
def build_forward_call_graph(model: ProgramModel) -> dict[str, set[str]]:
    """Build a map from caller to callees."""
    graph: dict[str, set[str]] = {}

    for call_site in model.call_sites:
        caller = call_site.caller_qualified or f"{call_site.file}::{call_site.caller_function}"
        callee = call_site.callee_qualified or call_site.callee_name  # FALLBACK TO BARE NAME

        if caller not in graph:
            graph[caller] = set()
        graph[caller].add(callee)

    return graph
```

**Key line**: `callee = call_site.callee_qualified or call_site.callee_name`

When `callee_qualified` is `None`, we use the bare function name. This means:
- Resolved: `graph["api.py::handler"] = {"users.py::UserService.get_user"}`
- Unresolved: `graph["api.py::handler"] = {"process"}` (just the bare name)

### The Propagation Loop (propagation.py:243-399)

```python
def propagate_exceptions(
    model: ProgramModel,
    max_iterations: int = 100,
    resolution_mode: ResolutionMode = "default",
    stub_library: StubLibrary | None = None,
) -> PropagationResult:
    """
    Propagate exceptions through the call graph.

    Resolution modes:
    - strict: Only follow resolved calls (no name_fallback or polymorphic)
    - default: Normal propagation with name fallback
    - aggressive: Include fuzzy matching (not yet implemented)
    """

    # ... setup code ...

    # Build a mapping from simple names to qualified names
    # This enables the name_fallback lookup
    name_to_qualified: dict[str, list[str]] = {}
    for qualified_key in propagated:
        simple_name = qualified_key.split("::")[-1].split(".")[-1]
        if simple_name not in name_to_qualified:
            name_to_qualified[simple_name] = []
        name_to_qualified[simple_name].append(qualified_key)
```

This builds a reverse index: `{"process": ["file1.py::process", "file2.py::Service.process"]}`

### The Name Fallback Mechanism (propagation.py:313-345)

This is the critical section:

```python
for caller, callees in forward_graph.items():
    # ... setup ...

    for callee in callees:
        call_site = call_site_lookup.get((caller, callee))
        expanded_callees = expand_polymorphic_call(
            callee, model.exception_hierarchy, method_to_qualified
        )
        is_polymorphic = len(expanded_callees) > 1

        for expanded_callee in expanded_callees:
            used_name_fallback = False
            callee_exceptions = propagated.get(expanded_callee, set())
            callee_evidence = propagated_evidence.get(expanded_callee, {})

            # ============================================
            # NAME FALLBACK HAPPENS HERE
            # ============================================
            if not callee_exceptions:
                # No exceptions found for this callee key
                # Try matching by simple name
                callee_simple = (
                    expanded_callee.split("::")[-1].split(".")[-1]
                    if "::" in expanded_callee
                    else expanded_callee.split(".")[-1]
                )
                for qualified_key in name_to_qualified.get(callee_simple, []):
                    callee_exceptions = callee_exceptions | propagated.get(
                        qualified_key, set()
                    )
                    callee_evidence = {
                        **callee_evidence,
                        **propagated_evidence.get(qualified_key, {}),
                    }
                    if callee_exceptions:
                        used_name_fallback = True
            # ============================================

            # Strict mode rejects fallback results
            if resolution_mode == "strict" and (used_name_fallback or is_polymorphic):
                continue

            # ... propagate exceptions ...
```

### What This Means Concretely

**Scenario**: Call graph contains:
- `api.py::handler` calls `"process"` (unresolved bare name)
- `services.py::DataService.process` raises `ValidationError`
- `utils.py::process` raises `IOError`

**What happens**:
1. Look up `propagated.get("process")` → empty (bare names aren't keys)
2. Name fallback: search `name_to_qualified.get("process")` → `["services.py::DataService.process", "utils.py::process"]`
3. Union all their exceptions: `{ValidationError, IOError}`
4. Both get propagated to `handler`

**Result**: `handler` is reported as potentially raising both `ValidationError` AND `IOError`, even though it probably only calls one of them.

## The Precision Problem

### False Positive Scenario

```python
# users/service.py
class UserService:
    def save(self):  # raises ValidationError
        validate(self.data)
        self.db.insert(self.data)

# documents/service.py
class DocumentService:
    def save(self):  # raises StorageError
        self.storage.upload(self.file)

# api/routes.py
def create_user(request):
    user = UserService(request.data)
    user.save()  # Unresolved: we don't track that `user` is a UserService
```

**Analysis result**: `create_user` can raise `{ValidationError, StorageError}`

**Reality**: It can only raise `ValidationError`

**False positive**: `StorageError`

### True Positive Scenario

```python
# payments/processor.py
def process_stripe_payment(amount):  # Unique function name
    stripe.charge(amount)  # raises PaymentError

# api/routes.py
def checkout(request):
    process_stripe_payment(request.amount)  # Resolved via import
```

**Analysis result**: `checkout` can raise `PaymentError` ✓

### When Fallback Works Well

1. **Unique function names**: `process_stripe_payment`, `validate_user_email`, `send_welcome_notification`
2. **Single implementation**: Only one `save()` in the entire codebase
3. **Domain-specific names**: Business logic tends to have unique names

### When Fallback Fails

1. **Generic names**: `save`, `get`, `process`, `run`, `execute`, `handle`
2. **Common patterns**: `validate`, `serialize`, `to_dict`
3. **Multiple implementations**: Same method name in different classes

## The Strict Mode Problem

Current `--strict` mode (propagation.py:344):

```python
if resolution_mode == "strict" and (used_name_fallback or is_polymorphic):
    continue  # Skip this edge entirely
```

This is **too aggressive**. It rejects ALL name_fallback results, even unambiguous ones.

**httpbin dogfooding result**:
- Default mode: Found 3 real bugs (100% precision at route level)
- Strict mode: Found 0 issues

The real bugs were rejected because SOME edge in the call chain used name_fallback.

## Potential Improvements

### Option 1: Track Match Ambiguity

```python
# Instead of just used_name_fallback: bool, track:
@dataclass
class FallbackInfo:
    used: bool
    match_count: int  # How many functions matched the name
    matched_qualified: list[str]  # Which ones

# Then in strict mode:
if resolution_mode == "strict":
    if fallback.used and fallback.match_count > 1:
        continue  # Ambiguous, reject
    # Unambiguous fallback is OK
```

### Option 2: Confidence Tiers in Output

```
Escaping exceptions from handler:

HIGH CONFIDENCE:
  ValidationError (via validate_user → raise, all edges resolved)

MEDIUM CONFIDENCE:
  DatabaseError (via save → db.insert, 1 unambiguous fallback)

LOW CONFIDENCE:
  StorageError (via save, 3 possible matches: UserService.save, DocService.save, CacheService.save)
```

### Option 3: Type Hint Integration

If we had type information from Pyright/mypy:

```python
def handler(service: UserService):
    service.save()  # NOW we know it's UserService.save
```

This would eliminate most fallback cases in typed codebases.

## Comparison with Other Tools

| Tool | Resolution Strategy | Dynamic Python Handling |
|------|--------------------|-----------------------|
| **Pyright** | Type inference | Requires type hints for accuracy |
| **mypy** | Type inference | Requires type hints |
| **Pylint** | Basic scope analysis | Limited cross-function tracking |
| **Flow** | Import + constructor + name_fallback | Works without hints, lower precision |

Flow's approach is **pragmatic**: it works on untyped codebases but trades precision for recall.

## Metrics from Dogfooding

### httpbin (Flask, 3k LOC, minimal type hints)

| Mode | Issues Found | True Positives | Precision |
|------|--------------|----------------|-----------|
| Default | 3 routes | 3 | 100% |
| Strict | 0 | 0 | N/A |

### requests (library, 11k LOC, well-typed)

Not applicable - libraries are supposed to raise exceptions. Flow correctly identified 34 raise sites but this isn't a "bug" for libraries.

## Open Questions for Expert Review

1. **Is the name_fallback approach fundamentally sound?** Or does it introduce too much noise for production use?

2. **Should we pursue type hint integration?** Pyright has an API. Would combining Flow's propagation with Pyright's type resolution give us the best of both worlds?

3. **Is the confidence model correct?** Currently:
   - `name_fallback` → low confidence
   - `return_type` → medium confidence
   - Everything else → high confidence

4. **What's the right default?** Currently `--strict` is too aggressive. Should we:
   - Make unambiguous fallback the default
   - Add a `--confident` mode between strict and default
   - Show ambiguity in output and let users decide

5. **Is fixpoint iteration the right algorithm?** Currently we iterate until no changes, up to 100 iterations. Are there cases where this doesn't converge or produces incorrect results?

## Code Locations

| Component | File | Lines |
|-----------|------|-------|
| CallSite model | `flow/models.py` | 97-108 |
| ResolutionKind | `flow/models.py` | 85-94 |
| Confidence scoring | `flow/models.py` | 132-138 |
| Call extraction | `flow/extractor.py` | 362-415 |
| Forward graph building | `flow/propagation.py` | 63-75 |
| Name fallback logic | `flow/propagation.py` | 313-345 |
| Strict mode check | `flow/propagation.py` | 344-345 |
| Propagation loop | `flow/propagation.py` | 297-392 |
