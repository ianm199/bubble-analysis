"""Simple timing instrumentation for performance analysis."""

from __future__ import annotations

import atexit
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


@dataclass
class TimingStats:
    """Collected timing statistics."""

    timings: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    enabled: bool = False
    _console: Console | None = None


_stats = TimingStats()


def enable(console: Console | None = None) -> None:
    """Enable timing collection."""
    _stats.enabled = True
    _stats.timings.clear()
    _stats.counts.clear()
    _stats._console = console
    atexit.register(_print_report_on_exit)


def disable() -> None:
    """Disable timing collection."""
    _stats.enabled = False


def is_enabled() -> bool:
    """Check if timing is enabled."""
    return _stats.enabled


@contextmanager
def timed(name: str) -> Generator[None, None, None]:
    """Context manager to time a block of code."""
    if not _stats.enabled:
        yield
        return

    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start

    _stats.timings[name] = _stats.timings.get(name, 0.0) + elapsed
    _stats.counts[name] = _stats.counts.get(name, 0) + 1


def record(name: str, elapsed: float) -> None:
    """Record a timing directly."""
    if not _stats.enabled:
        return
    _stats.timings[name] = _stats.timings.get(name, 0.0) + elapsed
    _stats.counts[name] = _stats.counts.get(name, 0) + 1


def get_report() -> dict[str, dict[str, float | int]]:
    """Get timing report as dict."""
    return {
        name: {
            "total_seconds": _stats.timings[name],
            "count": _stats.counts[name],
            "avg_ms": (_stats.timings[name] / _stats.counts[name]) * 1000,
        }
        for name in sorted(_stats.timings, key=lambda k: _stats.timings[k], reverse=True)
    }


def format_report() -> str:
    """Format timing report as a string."""
    report = get_report()
    if not report:
        return "No timing data collected."

    lines = ["", "Timing breakdown:"]
    for name, data in report.items():
        total = data["total_seconds"]
        count = data["count"]
        if count == 1:
            lines.append(f"  {name:30s} {total:>8.3f}s")
        else:
            avg_ms = data["avg_ms"]
            lines.append(f"  {name:30s} {total:>8.3f}s  ({count:,} calls, {avg_ms:.2f}ms avg)")

    return "\n".join(lines)


def _print_report_on_exit() -> None:
    """Print timing report on program exit."""
    if not _stats.enabled or not _stats.timings:
        return

    report_str = format_report()
    if _stats._console:
        _stats._console.print(report_str)
    else:
        print(report_str)
