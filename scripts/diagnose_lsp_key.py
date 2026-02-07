"""Diagnose why the LSP hover returns empty results for a function.

Compares the key the LSP would construct with what the propagation layer
actually uses. Run against a target project to see the mismatch.

Usage:
    python scripts/diagnose_lsp_key.py /path/to/project path/to/file.py function_name
    python scripts/diagnose_lsp_key.py ~/PycharmProjects/poc backend/agent/routes.py start_sandbox_agent
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: python scripts/diagnose_lsp_key.py <project_root> <relative_file> <function_name>")
        sys.exit(1)

    project_root = Path(sys.argv[1]).expanduser().resolve()
    relative_file = sys.argv[2]
    function_name = sys.argv[3]

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bubble.extractor import extract_from_directory
    from bubble.propagation import (
        build_forward_call_graph,
        compute_exception_flow,
        compute_forward_reachability,
        propagate_exceptions,
    )

    print(f"Project root: {project_root}")
    print(f"Target: {relative_file} :: {function_name}")
    print()

    print("Building model...")
    model = extract_from_directory(project_root)
    print(f"  {len(model.functions)} functions, {len(model.raise_sites)} raise sites")
    print()

    print("=" * 60)
    print("1. MODEL.FUNCTIONS KEY FORMAT (single colon)")
    print("=" * 60)
    single_colon_matches = [
        k for k in model.functions
        if function_name in k and relative_file in k
    ]
    print(f"  Keys matching '{function_name}' + '{relative_file}': {single_colon_matches}")

    all_func_keys_for_file = [k for k in model.functions if relative_file in k]
    print(f"  All keys for file ({len(all_func_keys_for_file)} total):")
    for k in all_func_keys_for_file[:10]:
        print(f"    {k}")
    if len(all_func_keys_for_file) > 10:
        print(f"    ... and {len(all_func_keys_for_file) - 10} more")
    print()

    print("=" * 60)
    print("2. FUNCTIONDEF FIELDS")
    print("=" * 60)
    for key, func in model.functions.items():
        if function_name in func.qualified_name and relative_file in (func.file or key):
            print(f"  key:            {key}")
            print(f"  func.file:      {func.file}")
            print(f"  func.name:      {func.name}")
            print(f"  func.qual_name: {func.qualified_name}")
            print(f"  func.line:      {func.line}")
            print(f"  func.class:     {func.class_name}")
            print()
    print()

    print("=" * 60)
    print("3. FORWARD GRAPH KEY FORMAT (double colon)")
    print("=" * 60)
    forward_graph = build_forward_call_graph(model)
    double_colon_matches = [
        k for k in forward_graph
        if function_name in k and relative_file in k
    ]
    print(f"  Forward graph keys matching: {double_colon_matches}")
    print()

    lsp_key = f"{relative_file}::{function_name}"
    print("=" * 60)
    print(f"4. LSP CONSTRUCTED KEY: '{lsp_key}'")
    print("=" * 60)
    print(f"  In forward_graph? {lsp_key in forward_graph}")
    if lsp_key in forward_graph:
        callees = forward_graph[lsp_key]
        print(f"  Callees ({len(callees)}): {list(callees)[:5]}...")

    close_matches = [k for k in forward_graph if function_name in k]
    if close_matches and lsp_key not in forward_graph:
        print(f"  Close matches in forward_graph:")
        for m in close_matches[:10]:
            print(f"    {m}")
    print()

    print("=" * 60)
    print("5. PROPAGATION TEST")
    print("=" * 60)
    for test_key in [lsp_key] + double_colon_matches:
        print(f"\n  Testing key: '{test_key}'")
        scope = compute_forward_reachability(test_key, model, forward_graph)
        print(f"  Forward reachability scope: {len(scope)} functions")

        if scope:
            propagation = propagate_exceptions(model, skip_evidence=True, scope=scope)
            flow = compute_exception_flow(test_key, model, propagation)
            print(f"  Uncaught: {list(flow.uncaught.keys())}")
            print(f"  Caught locally: {list(flow.caught_locally.keys())}")
            print(f"  Framework handled: {list(flow.framework_handled.keys())}")
        else:
            print(f"  EMPTY SCOPE - this is why hover shows nothing")
    print()

    print("=" * 60)
    print("6. RAISE SITES IN THIS FILE")
    print("=" * 60)
    file_raises = [r for r in model.raise_sites if relative_file in r.file]
    for r in file_raises[:10]:
        print(f"  {r.file}::{r.function} raises {r.exception_type} (line {r.line})")
    if not file_raises:
        print("  (none in this file)")
    print()

    print("=" * 60)
    print("7. ENTRYPOINTS MATCHING THIS FUNCTION")
    print("=" * 60)
    matching_ep = [e for e in model.entrypoints if function_name in e.function]
    for ep in matching_ep:
        print(f"  {ep.kind}: {ep.metadata}")
        print(f"    function: {ep.function}")
        print(f"    file: {ep.file}")
    if not matching_ep:
        print("  (none found)")


if __name__ == "__main__":
    main()
