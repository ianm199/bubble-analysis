# Performance Architecture

This document describes the caching layers, graph structures, and performance considerations for the flow analysis tool.

## Pipeline Overview

```
Python Files
     │
     ▼ (cached in SQLite)
┌──────────────────┐
│  FileExtraction  │  per-file: functions, calls, raises, catches
└────────┬─────────┘
         │
         ▼ (aggregated)
┌──────────────────┐
│   ProgramModel   │  all files combined + hierarchy
└────────┬─────────┘
         │
         ▼ (cached in-memory)
┌──────────────────┐
│PropagationResult │  propagated_raises, evidence, catches_by_function
└────────┬─────────┘
         │
         ├──→ forward_graph (build once, reuse)
         ├──→ name_to_qualified (build once, reuse)
         │
         ▼
┌──────────────────┐
│  Query Results   │  EscapesResult, AuditResult, etc.
└──────────────────┘
```

## Caching Layers

### 1. SQLite File Cache (Persistent)

**Location:** `.flow/cache.sqlite`

**Key:** file path + mtime + size (invalidates on file change)

**Value:** Serialized `FileExtraction` containing:
- Functions and classes
- Raise sites, catch sites, call sites
- Import maps
- Detected entrypoints and handlers

**Impact:** Reduces cold extraction from minutes to sub-second on subsequent runs.

### 2. Propagation Cache (In-Memory)

**Location:** Module-level `_propagation_cache` dict in `propagation.py`

**Key:** `(id(model), resolution_mode, id(stub_library))`

**Value:** `PropagationResult` with propagated exceptions and evidence

**Lifetime:** Single process invocation

**Purpose:** Multiple queries (raises, escapes, audit) share the same propagation without recomputing.

**API:**
```python
from flow.propagation import clear_propagation_cache
clear_propagation_cache()  # For testing or memory management
```

### 3. Hierarchy Subclass Cache (Per-Instance)

**Location:** `ClassHierarchy._subclass_cache` dict

**Key:** `(child_class, parent_class)` tuple

**Value:** `bool` (is subclass?)

**Purpose:** Memoize BFS traversal for `is_subclass_of()` checks

**Invalidation:** Cleared automatically when `add_class()` is called

**Typical hit ratio:** 20:1 to 50:1 on real codebases

## Graph Structures

### Forward Call Graph

Built by `build_forward_call_graph(model)`.

```
caller → set of callees
"api/routes.py::get_user" → {"services/user.py::UserService.fetch", "utils.py::validate"}
```

**Used for:** Reachability analysis ("what can this function call?")

### Reverse Call Graphs

Built by `build_reverse_call_graph(model)`.

Returns two graphs:

1. **Qualified graph:** `callee_qualified → set of callers`
2. **Name graph:** `callee_simple_name → set of callers`

**Used for:** "Who calls this function?" queries with fallback

### Name-to-Qualified Map

Built by `build_name_to_qualified(propagation)`.

```
simple_name → list of qualified names
"process" → ["svc.py::ServiceA.process", "svc.py::ServiceB.process"]
```

**Used for:** Resolving bare function names when qualified lookup fails

## Performance Patterns

### Pattern: Build Once, Reuse

When processing multiple items (e.g., auditing N entrypoints):

```python
# BAD - rebuilds graphs N times
for entrypoint in entrypoints:
    compute_reachable_functions(entrypoint, model, propagation)  # rebuilds internally

# GOOD - build once, pass in
forward_graph = build_forward_call_graph(model)
name_to_qualified = build_name_to_qualified(propagation)

for entrypoint in entrypoints:
    compute_reachable_functions(
        entrypoint, model, propagation,
        forward_graph=forward_graph,
        name_to_qualified=name_to_qualified,
    )
```

### Pattern: ProcessPoolExecutor for Extraction

File parsing with libcst is CPU-bound. Python's GIL prevents true parallelism with threads.

```python
# Uses ProcessPoolExecutor (not ThreadPoolExecutor)
# Each worker is a separate Python process - no GIL contention
with ProcessPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(_extract_single_file_for_process, fp, rp): ...}
```

**Note:** Cache lookups happen in the main process before dispatching to workers (SQLite connections can't cross process boundaries).

## Timing Instrumentation

Enable with `--timing` flag:

```bash
flow --timing flask audit -d /path/to/project
```

Output:
```
Timing breakdown:
  parallel_extraction               0.282s
  propagation_fixpoint              1.411s
  propagation_setup                 0.015s
  file_discovery                    0.054s
  hierarchy_lookup                  0.004s  (1,761 calls)
  model_aggregation                 0.003s
  hierarchy_cache_hit               0.000s  (22,927 calls)
```

### What Each Phase Measures

| Phase | What it includes |
|-------|------------------|
| `file_discovery` | `rglob("*.py")` to find Python files |
| `parallel_extraction` | libcst parsing (or cache loading) |
| `cache_writes` | Writing extraction results to SQLite |
| `model_aggregation` | Combining per-file extractions into ProgramModel |
| `propagation_setup` | Building call graphs and initial state |
| `propagation_fixpoint` | Iterating until no new exceptions propagate |
| `hierarchy_lookup` | Uncached `is_subclass_of()` BFS traversals |
| `hierarchy_cache_hit` | Cached hierarchy lookups (count only) |

## Benchmarks

### Typical Performance (with cache)

| Codebase Size | Files | Call Sites | Stats | Audit |
|---------------|-------|------------|-------|-------|
| Small (~100 files) | 100 | 2k | <0.5s | <1s |
| Medium (~500 files) | 500 | 15k | <1s | <3s |
| Large (~1000 files) | 1000 | 40k | <2s | <5s |

### Cold vs Cached Extraction

| Codebase | Cold (no cache) | Cached |
|----------|-----------------|--------|
| 500 files | ~45s | <0.1s |
| 1000 files | ~100s | <0.3s |

The SQLite cache provides 100-500x speedup on subsequent runs.
