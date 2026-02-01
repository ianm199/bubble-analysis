"""Typed enums for code flow analysis.

Centralizes all enum types to prevent magic string comparisons throughout the codebase.
All enums inherit from (str, Enum) to support JSON serialization and string comparison.
"""

from enum import Enum


class EntrypointKind(str, Enum):
    """Types of entrypoints where external input enters the program."""

    HTTP_ROUTE = "http_route"
    QUEUE_HANDLER = "queue_handler"
    CLI_SCRIPT = "cli_script"
    SCHEDULED_JOB = "scheduled_job"
    TEST = "test"
    UNKNOWN = "unknown"


class OutputFormat(str, Enum):
    """Output format for CLI commands."""

    JSON = "json"
    TEXT = "text"


class ConfidenceLevel(str, Enum):
    """Confidence level for exception propagation paths."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Framework(str, Enum):
    """Supported web frameworks."""

    FLASK = "flask"
    FASTAPI = "fastapi"
    CLI = "cli"


class ResolutionMode(str, Enum):
    """Resolution mode for call graph analysis."""

    STRICT = "strict"
    DEFAULT = "default"
    AGGRESSIVE = "aggressive"


class ResolutionKind(str, Enum):
    """How a call site was resolved to its target."""

    IMPORT = "import"
    SELF = "self"
    CONSTRUCTOR = "constructor"
    RETURN_TYPE = "return_type"
    MODULE_ATTRIBUTE = "module_attribute"
    NAME_FALLBACK = "name_fallback"
    POLYMORPHIC = "polymorphic"
    STUB = "stub"
    UNRESOLVED = "unresolved"
    FASTAPI_DEPENDS = "fastapi_depends"
    IMPLICIT_DISPATCH = "implicit_dispatch"
