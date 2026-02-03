#!/usr/bin/env python3
"""Quick test of scoped propagation on Sentry."""

import sys
import time
from pathlib import Path

from bubble.extractor import extract_from_directory
from bubble.propagation import (
    build_forward_call_graph,
    compute_forward_reachability,
    propagate_exceptions,
    clear_propagation_cache,
)

def p(msg: str) -> None:
    print(msg, flush=True)

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/sentry/src/sentry")

    p(f"Loading model from {target}...")
    t0 = time.perf_counter()
    model = extract_from_directory(target)
    p(f"  Loaded: {time.perf_counter() - t0:.1f}s")
    p(f"  Call sites: {len(model.call_sites)}, Functions: {len(model.functions)}")

    p("Building forward graph...")
    t0 = time.perf_counter()
    forward_graph = build_forward_call_graph(model)
    p(f"  Built: {time.perf_counter() - t0:.2f}s, {len(forward_graph)} callers")

    test_func = "api/endpoints/organization_stats.py::OrganizationStatsEndpoint.get"
    p(f"Computing scope for {test_func}...")
    t0 = time.perf_counter()
    scope = compute_forward_reachability(test_func, model, forward_graph)
    p(f"  Scope: {time.perf_counter() - t0:.2f}s, {len(scope)} functions (vs {len(model.functions)} total)")

    p("Running scoped propagation...")
    clear_propagation_cache()
    t0 = time.perf_counter()
    prop = propagate_exceptions(model, skip_evidence=True, scope=scope)
    p(f"  Propagation: {time.perf_counter() - t0:.2f}s, {len(prop.propagated_raises)} functions with raises")

    p("Running full propagation (for comparison)...")
    clear_propagation_cache()
    t0 = time.perf_counter()
    prop_full = propagate_exceptions(model, skip_evidence=True)
    p(f"  Propagation: {time.perf_counter() - t0:.2f}s, {len(prop_full.propagated_raises)} functions with raises")

if __name__ == "__main__":
    main()
