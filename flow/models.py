"""Data models for code flow analysis."""

from dataclasses import dataclass, field

from flow.enums import ConfidenceLevel, EntrypointKind, ResolutionKind
from flow.integrations.base import (
    Entrypoint,
    GlobalHandler,
)

__all__ = [
    "FunctionDef",
    "ClassDef",
    "RaiseSite",
    "CatchSite",
    "ResolutionKind",
    "CallSite",
    "ResolutionEdge",
    "ExceptionEvidence",
    "compute_confidence",
    "Entrypoint",
    "EntrypointKind",
    "GlobalHandler",
    "DependencyEdge",
    "ImportInfo",
    "ClassHierarchy",
    "ExceptionHierarchy",
    "ProgramModel",
]


@dataclass
class FunctionDef:
    """A function or method definition."""

    name: str
    qualified_name: str
    file: str
    line: int
    is_method: bool
    is_async: bool
    class_name: str | None = None
    return_type: str | None = None


@dataclass
class ClassDef:
    """A class definition."""

    name: str
    qualified_name: str
    file: str
    line: int
    bases: list[str] = field(default_factory=list)
    is_abstract: bool = False
    abstract_methods: set[str] = field(default_factory=set)


@dataclass
class RaiseSite:
    """A location where an exception is raised."""

    file: str
    line: int
    function: str
    exception_type: str
    is_bare_raise: bool
    code: str
    message_expr: str | None = None


@dataclass
class CatchSite:
    """A location where exceptions are caught."""

    file: str
    line: int
    function: str
    caught_types: list[str]
    has_bare_except: bool
    has_reraise: bool


@dataclass
class CallSite:
    """A location where a function is called."""

    file: str
    line: int
    caller_function: str
    callee_name: str
    is_method_call: bool
    caller_qualified: str | None = None
    callee_qualified: str | None = None
    resolution_kind: ResolutionKind = ResolutionKind.UNRESOLVED


@dataclass
class ResolutionEdge:
    """An edge in the call path with resolution metadata."""

    caller: str
    callee: str
    file: str
    line: int
    resolution_kind: ResolutionKind
    is_heuristic: bool


@dataclass
class ExceptionEvidence:
    """Evidence for how an exception propagates to a function."""

    raise_site: "RaiseSite"
    call_path: list[ResolutionEdge]
    confidence: ConfidenceLevel


def compute_confidence(edges: list[ResolutionEdge]) -> ConfidenceLevel:
    """Compute confidence level based on resolution kinds in the path."""
    if any(
        e.resolution_kind in (ResolutionKind.NAME_FALLBACK, ResolutionKind.POLYMORPHIC)
        for e in edges
    ):
        return ConfidenceLevel.LOW
    if any(e.resolution_kind == ResolutionKind.RETURN_TYPE for e in edges):
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.HIGH


@dataclass
class DependencyEdge:
    """An implicit dependency (e.g., FastAPI Depends)."""

    dependent_file: str
    dependent_function: str
    dependency_name: str
    kind: str


@dataclass
class ImportInfo:
    """An import statement in a module."""

    file: str
    module: str
    name: str
    alias: str | None = None
    is_from_import: bool = False


@dataclass
class ClassHierarchy:
    """Complete class hierarchy with inheritance relationships."""

    classes: dict[str, ClassDef] = field(default_factory=dict)
    parent_map: dict[str, list[str]] = field(default_factory=dict)
    child_map: dict[str, list[str]] = field(default_factory=dict)

    def add_class(self, cls: ClassDef) -> None:
        """Add a class to the hierarchy."""
        self.classes[cls.name] = cls
        self.parent_map[cls.name] = cls.bases

        for base in cls.bases:
            base_simple = base.split(".")[-1]
            if base_simple not in self.child_map:
                self.child_map[base_simple] = []
            if cls.name not in self.child_map[base_simple]:
                self.child_map[base_simple].append(cls.name)

    def get_all_subclasses(self, class_name: str) -> set[str]:
        """Get all subclasses of a class (direct and indirect)."""
        result: set[str] = set()
        to_visit = [class_name]

        while to_visit:
            current = to_visit.pop()
            for child in self.child_map.get(current, []):
                if child not in result:
                    result.add(child)
                    to_visit.append(child)

        return result

    def get_subclasses(self, class_name: str) -> set[str]:
        """Alias for get_all_subclasses for backwards compatibility."""
        return self.get_all_subclasses(class_name)

    def is_subclass_of(self, child: str, parent: str) -> bool:
        """Check if child is a subclass of parent."""
        if child == parent:
            return True

        visited: set[str] = set()
        to_check = [child]

        while to_check:
            current = to_check.pop()
            if current in visited:
                continue
            visited.add(current)

            parents = self.parent_map.get(current, [])
            for p in parents:
                p_simple = p.split(".")[-1]
                if p_simple == parent or p == parent:
                    return True
            to_check.extend(p.split(".")[-1] for p in parents)

        return False

    def is_abstract_method(self, class_name: str, method_name: str) -> bool:
        """Check if a method is abstract on a class."""
        cls = self.classes.get(class_name)
        if cls:
            return method_name in cls.abstract_methods
        return False

    def get_concrete_implementations(
        self, base_class: str, method_name: str
    ) -> list[tuple[str, ClassDef]]:
        """Get all concrete implementations of an abstract method.

        Returns list of (class_name, class_def) tuples.
        """
        if not self.is_abstract_method(base_class, method_name):
            return []

        implementations: list[tuple[str, ClassDef]] = []
        subclasses = self.get_all_subclasses(base_class)

        for subclass_name in subclasses:
            cls = self.classes.get(subclass_name)
            if cls and method_name not in cls.abstract_methods:
                implementations.append((subclass_name, cls))

        return implementations


ExceptionHierarchy = ClassHierarchy


@dataclass
class ProgramModel:
    """The complete model of a codebase for analysis."""

    functions: dict[str, FunctionDef] = field(default_factory=dict)
    classes: dict[str, ClassDef] = field(default_factory=dict)
    raise_sites: list[RaiseSite] = field(default_factory=list)
    catch_sites: list[CatchSite] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)
    entrypoints: list[Entrypoint] = field(default_factory=list)
    global_handlers: list[GlobalHandler] = field(default_factory=list)
    exception_hierarchy: ExceptionHierarchy = field(default_factory=ExceptionHierarchy)
    imports: list[ImportInfo] = field(default_factory=list)
    import_maps: dict[str, dict[str, str]] = field(default_factory=dict)
    return_types: dict[str, str] = field(default_factory=dict)
    detected_frameworks: set[str] = field(default_factory=set)

    def get_function_by_name(self, name: str, file: str | None = None) -> FunctionDef | None:
        """Find a function by name, optionally scoped to a file."""
        for key, func in self.functions.items():
            if file and not key.startswith(file):
                continue
            if func.name == name or func.qualified_name == name:
                return func
        return None

    def get_callers(self, function_name: str) -> list[CallSite]:
        """Get all call sites that call a function by name."""
        return [c for c in self.call_sites if c.callee_name == function_name]

    def get_callers_qualified(self, qualified_name: str) -> list[CallSite]:
        """Get all call sites that call a function by qualified name."""
        return [c for c in self.call_sites if c.callee_qualified == qualified_name]

    def resolve_name(self, name: str, file: str) -> str | None:
        """Resolve a name to its qualified form using the file's import map."""
        import_map = self.import_maps.get(file, {})
        return import_map.get(name)

    def get_return_type(self, qualified_name: str) -> str | None:
        """Get the return type of a function by its qualified name."""
        return self.return_types.get(qualified_name)
