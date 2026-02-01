# Propagation Performance Analysis

## Problem Statement

Exception propagation on large codebases is slow. On Sentry (7,469 files, 134k call sites), propagation takes ~5 minutes after memoization optimization (was 14+ minutes before).

## What Propagation Does

Given a call graph and raise sites, compute which exceptions can escape from each function:

```
If function A raises ValueError and B calls A,
then B can also raise ValueError (unless B catches it).
```

This is a fixpoint computation over the call graph.

## Current Algorithm

```python
# Simplified pseudocode
propagated = {func: direct_raises[func] for func in functions}

for iteration in range(max_iterations):
    changed = False
    for caller, callees in call_graph.items():
        for callee in callees:
            for exc_type in propagated[callee]:
                if not is_caught(exc_type, caller):
                    if exc_type not in propagated[caller]:
                        propagated[caller].add(exc_type)
                        changed = True
    if not changed:
        break
```

## Complexity Analysis

Let:
- `V` = number of functions (vertices)
- `E` = number of call edges
- `X` = number of unique exception types
- `C` = average catch sites per function
- `I` = number of iterations until fixpoint

### Per-Iteration Cost

```
O(E × X × C)
```

For each edge, we check each exception type against each catch site.

### Total Cost

```
O(I × E × X × C)
```

### Observed Values

| Codebase | V (functions) | E (call sites) | X (exc types) | C (catches) | I (iterations) |
|----------|---------------|----------------|---------------|-------------|----------------|
| Small API | 1,707 | 13,321 | ~50 | ~3 | 4-5 |
| Full Sentry | 22,905 | 134,516 | ~200 | ~5 | 10-20 |

### Scaling

From small to Sentry:
- E grows 10x (13k → 134k)
- X grows 4x (50 → 200)
- I grows 2-4x (5 → 10-20)

Expected slowdown: **80-160x**

Observed: Small API = 0.36s, Sentry = 312s → **867x slower**

The extra slowdown comes from:
1. Name fallback lookups (unresolved calls require string matching)
2. Evidence tracking (building tuple paths for each propagation)
3. Polymorphic expansion (abstract method → all implementations)

## Current Optimizations

### 1. Memoized Fallback Lookups (implemented)

Before: `_scoped_fallback_lookup()` called for every unresolved edge, every iteration.

After: Results cached by `(callee_name, is_method, caller_file)`.

Impact: **14+ min → 5.2 min** (2.7x faster)

### 2. Pre-built Graph Structures (implemented earlier)

`forward_graph`, `name_to_qualified` built once before loop, not per-entrypoint.

Impact: Audit loop went from 22 min → 4 seconds.

## Potential Optimizations

### A. Skip Evidence Tracking

Currently we build a call path for each propagated exception:

```python
new_path = (edge,) + prop_raise.path
propagated_evidence[caller][key] = PropagatedRaise(
    exception_type=exc_type,
    raise_site=prop_raise.raise_site,
    path=new_path,
)
```

This creates tuples for every propagation. With 25k+ propagated functions and multiple exceptions each, this is millions of tuple allocations.

**Proposal**: Add `--fast` mode that skips evidence tracking.

Expected impact: 20-40% speedup (estimate based on tuple overhead).

### B. Worklist-Based Algorithm

Current: Iterate over ALL edges every iteration, even if nothing changed for most.

Proposed:
```python
worklist = set(functions_with_direct_raises)
while worklist:
    callee = worklist.pop()
    for caller in reverse_graph[callee]:
        new_exceptions = propagated[callee] - caught_by[caller]
        if new_exceptions - propagated[caller]:
            propagated[caller] |= new_exceptions
            worklist.add(caller)
```

This only processes functions whose callees changed.

Expected impact: Potentially 5-10x faster for sparse propagation.

Complexity: `O(E × X × C)` total (amortized), vs `O(I × E × X × C)` current.

### C. Batch Catch Checking

Current: For each exception, iterate through all catch sites to check if caught.

Proposed: Pre-compute `caught_types_by_function` set once, use set intersection.

```python
caught_set = precomputed_catches[caller]
uncaught = propagated[callee] - caught_set
```

This requires handling exception hierarchy (subclass relationships) upfront.

Expected impact: 2-3x faster catch checking.

### D. Depth-Limited Propagation

Stop propagating after N hops from raise site. Loses precision but bounds runtime.

```python
if len(path) > max_depth:
    continue
```

With `max_depth=10`, would catch most real-world call chains.

Expected impact: Bounds worst-case, may miss deep chains.

### E. Demand-Driven Propagation

Only compute what's needed for specific entrypoints:

1. BFS forward from entrypoint to find reachable functions
2. Collect raise sites in reachable set
3. Propagate only within that subgraph

For auditing 52 Django views, this could be 52 small propagations instead of 1 giant one.

Expected impact: Proportional to entrypoint reach (maybe 10-50x faster per entrypoint).

Downside: Repeated work if entrypoints overlap significantly.

## Recommendations

### Short-term (low risk)
1. **Skip evidence tracking** via `--fast` flag
2. **Batch catch checking** with pre-computed sets

### Medium-term (algorithm change)
3. **Worklist algorithm** - most impactful, requires refactor

### Long-term (architecture)
4. **Demand-driven propagation** for audit commands
5. **Incremental propagation** for watch mode / IDE integration

## Benchmark Commands

```bash
# Time just propagation
python3.11 -c "
from flow.extractor import extract_from_directory
from flow.propagation import propagate_exceptions
from pathlib import Path
import time

model = extract_from_directory(Path('/tmp/sentry'))
start = time.time()
result = propagate_exceptions(model)
print(f'Propagation: {time.time() - start:.2f}s')
"

# Full audit with timing breakdown
flow --timing django audit -d /tmp/sentry --no-cache
```

## Current Timing Data

### Sentry API Only (351 files)
```
parallel_extraction              30.2s
propagation_fixpoint              0.36s  ← fast
Total:                           ~31s
```

### Full Sentry (7,469 files)
```
parallel_extraction             104s
propagation_fixpoint            312s    ← slow
Total:                          ~7 min
```

### Superset (1,129 files) - for comparison
```
parallel_extraction              24s
propagation_fixpoint              2.8s
Total:                           ~27s
```

## Code Pointers

- Main loop: `flow/propagation.py:373-507`
- Fallback lookup: `flow/propagation.py:263-308`
- Evidence tracking: `flow/propagation.py:483-504`
- Catch checking: `flow/propagation.py:448-459`
