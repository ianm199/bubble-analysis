#!/usr/bin/env python3
"""Quick benchmark script for propagation performance testing.

Usage:
    python scripts/bench_propagation.py                    # Run all benchmarks
    python scripts/bench_propagation.py --target small     # Just small repos
    python scripts/bench_propagation.py --target medium    # Medium (Sentry API)
    python scripts/bench_propagation.py --profile          # With cProfile
"""

import argparse
import sys
import time
from pathlib import Path

TARGETS = {
    "tiny": Path(__file__).parent.parent / "tests/fixtures/flask_app",
    "small": Path.home() / "PycharmProjects/poc/backend",
    "flow": Path(__file__).parent.parent / "flow",
    "medium": Path("/tmp/sentry/src/sentry/api"),
    "large": Path("/tmp/superset"),
    "huge": Path("/tmp/sentry"),
}


def run_benchmark(target_path: Path, name: str, verbose: bool = True, skip_evidence: bool = False) -> dict:
    """Run propagation benchmark on a target directory."""
    from flow.extractor import extract_from_directory
    from flow.propagation import propagate_exceptions, clear_propagation_cache

    clear_propagation_cache()

    if not target_path.exists():
        print(f"  {name}: SKIP (path not found: {target_path})")
        return {}

    t0 = time.perf_counter()
    model = extract_from_directory(target_path)
    t_extract = time.perf_counter() - t0

    t0 = time.perf_counter()
    result = propagate_exceptions(model, skip_evidence=skip_evidence)
    t_propagate = time.perf_counter() - t0

    stats = {
        "name": name,
        "files": len(set(f.file for f in model.functions.values())),
        "functions": len(model.functions),
        "call_sites": len(model.call_sites),
        "raise_sites": len(model.raise_sites),
        "propagated": len(result.propagated_raises),
        "t_extract": t_extract,
        "t_propagate": t_propagate,
    }

    if verbose:
        print(f"  {name}:")
        print(f"    Files: {stats['files']}, Functions: {stats['functions']}, Calls: {stats['call_sites']}")
        print(f"    Extract: {t_extract:.3f}s, Propagate: {t_propagate:.3f}s")
        print(f"    Propagated raises: {stats['propagated']} functions")

    return stats


def run_with_profile(target_path: Path, name: str):
    """Run with cProfile and print top functions."""
    import cProfile
    import pstats
    from io import StringIO

    from flow.extractor import extract_from_directory
    from flow.propagation import propagate_exceptions, clear_propagation_cache

    clear_propagation_cache()

    if not target_path.exists():
        print(f"  {name}: SKIP (path not found)")
        return

    model = extract_from_directory(target_path)
    print(f"  Model: {len(model.functions)} functions, {len(model.call_sites)} call sites")

    pr = cProfile.Profile()
    pr.enable()
    propagate_exceptions(model)
    pr.disable()

    s = StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumtime")
    ps.print_stats(20)
    print(s.getvalue())


def main():
    parser = argparse.ArgumentParser(description="Benchmark propagation performance")
    parser.add_argument("--target", choices=list(TARGETS.keys()) + ["all"], default="all")
    parser.add_argument("--profile", action="store_true", help="Run with cProfile")
    parser.add_argument("--repeat", type=int, default=1, help="Number of repetitions")
    parser.add_argument("--fast", action="store_true", help="Skip evidence tracking")
    parser.add_argument("--compare", action="store_true", help="Compare with and without --fast")
    args = parser.parse_args()

    print("Propagation Benchmark")
    print("=" * 50)

    if args.target == "all":
        targets = ["tiny", "small", "flow"]
    else:
        targets = [args.target]

    for name in targets:
        path = TARGETS[name]
        print(f"\nTarget: {name} ({path})")

        if args.profile:
            run_with_profile(path, name)
        elif args.compare:
            print("  Normal mode:")
            stats_normal = run_benchmark(path, name, skip_evidence=False)
            print("  Fast mode (skip_evidence):")
            stats_fast = run_benchmark(path, name, skip_evidence=True)
            if stats_normal and stats_fast:
                speedup = stats_normal["t_propagate"] / stats_fast["t_propagate"] if stats_fast["t_propagate"] > 0 else 0
                print(f"  Speedup: {speedup:.2f}x")
        else:
            for i in range(args.repeat):
                if args.repeat > 1:
                    print(f"  Run {i+1}/{args.repeat}")
                run_benchmark(path, name, skip_evidence=args.fast)


if __name__ == "__main__":
    main()
