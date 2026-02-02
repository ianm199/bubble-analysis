"""Result dataclasses for query functions.

These define the contract between queries and formatters.
All query functions return one of these typed results.
"""

from dataclasses import dataclass, field

from bubble.models import (
    CallSite,
    CatchSite,
    ClassHierarchy,
    Entrypoint,
    GlobalHandler,
    RaiseSite,
)
from bubble.propagation import ExceptionFlow


@dataclass
class RaisesResult:
    """Result of finding raise sites for an exception."""

    exception_type: str
    include_subclasses: bool
    types_searched: set[str]
    matches: list[RaiseSite]


@dataclass
class ExceptionClass:
    """Info about an exception class."""

    name: str
    bases: list[str]
    file: str | None
    line: int | None


@dataclass
class ExceptionsResult:
    """Result of listing exception hierarchy."""

    classes: dict[str, ExceptionClass]
    roots: set[str]
    hierarchy: ClassHierarchy


@dataclass
class StatsResult:
    """Result of codebase statistics."""

    functions: int
    classes: int
    raise_sites: int
    catch_sites: int
    call_sites: int
    entrypoints: int
    http_routes: int
    cli_scripts: int
    global_handlers: int
    imports: int


@dataclass
class CallersResult:
    """Result of finding callers of a function."""

    function_name: str
    calls: list[CallSite]
    suggestions: list[str] = field(default_factory=list)


@dataclass
class EntrypointTrace:
    """A single raise site traced to its entrypoints."""

    raise_site: RaiseSite
    paths: list[list[str]]
    entrypoints: list[Entrypoint]


@dataclass
class EntrypointsToResult:
    """Result of tracing exception to entrypoints."""

    exception_type: str
    include_subclasses: bool
    types_searched: set[str]
    traces: list[EntrypointTrace]


@dataclass
class EntrypointsResult:
    """Result of listing all entrypoints."""

    http_routes: list[Entrypoint]
    cli_scripts: list[Entrypoint]
    other: dict[str, list[Entrypoint]]


@dataclass
class EscapesResult:
    """Result of finding escaping exceptions."""

    function_name: str
    entrypoint: Entrypoint | None
    flow: ExceptionFlow
    global_handlers: list[GlobalHandler]


@dataclass
class CatchesResult:
    """Result of finding catch sites for an exception."""

    exception_type: str
    include_subclasses: bool
    types_searched: set[str]
    local_catches: list[CatchSite]
    global_handlers: list[GlobalHandler]
    raise_site_count: int = 0


@dataclass
class AuditIssue:
    """An entrypoint with uncaught exceptions."""

    entrypoint: Entrypoint
    uncaught: dict[str, list[RaiseSite]]
    caught: dict[str, list[RaiseSite]]


@dataclass
class AuditResult:
    """Result of auditing all entrypoints."""

    total_entrypoints: int
    issues: list[AuditIssue]
    clean_count: int


@dataclass
class CacheStats:
    """Result of cache statistics."""

    file_count: int
    size_bytes: int


@dataclass
class TraceNode:
    """A node in the trace tree."""

    function: str
    qualified: str
    direct_raises: list[str]
    propagated_raises: list[str]
    calls: list["TraceNode | PolymorphicNode"]


@dataclass
class PolymorphicNode:
    """A polymorphic call with multiple implementations."""

    function: str
    implementations: list[TraceNode]
    raises: list[str]


@dataclass
class TraceResult:
    """Result of tracing exception flow."""

    function_name: str
    entrypoint: Entrypoint | None
    root: TraceNode | None
    escaping_exceptions: set[str]


@dataclass
class SubclassInfo:
    """Info about a subclass."""

    name: str
    file: str | None
    line: int | None
    is_abstract: bool


@dataclass
class SubclassesResult:
    """Result of finding subclasses."""

    class_name: str
    base_class_file: str | None
    base_class_line: int | None
    is_abstract: bool
    abstract_methods: set[str]
    subclasses: list[SubclassInfo]


@dataclass
class InitResult:
    """Result of initializing .flow directory."""

    flow_dir: str
    functions_count: int
    http_routes_count: int
    cli_scripts_count: int
    exception_classes_count: int
    global_handlers_count: int
    frameworks_detected: list[str]
