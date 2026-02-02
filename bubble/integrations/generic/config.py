"""Configuration schema for generic framework detection."""

from dataclasses import dataclass, field
from fnmatch import fnmatch


@dataclass
class DecoratorRoutePattern:
    """Pattern for decorator-based routes like @app.route or @router.get.

    Examples:
        # Flask: @app.route("/path", methods=["GET"])
        DecoratorRoutePattern(
            decorator_pattern="*.route",
            path_source="arg[0]",
            method_source="kwarg[methods]",
        )

        # FastAPI: @router.get("/path")
        DecoratorRoutePattern(
            decorator_pattern="*.get",
            path_source="arg[0]",
            method_source="decorator_name",
        )

        # Flask-AppBuilder: @expose("/path")
        DecoratorRoutePattern(
            decorator_pattern="expose",
            path_source="arg[0]",
            method_source="kwarg[methods]",
        )
    """

    decorator_pattern: str
    path_source: str = "arg[0]"
    method_source: str = "kwarg[methods]"
    default_method: str = "GET"

    def matches_decorator(self, decorator_name: str) -> bool:
        """Check if this pattern matches a decorator name.

        Args:
            decorator_name: Name like "route", "get", or "expose"
        """
        return fnmatch(decorator_name, self.decorator_pattern)


@dataclass
class ClassRoutePattern:
    """Pattern for class-based views like Django APIView.

    Examples:
        # Django REST Framework
        ClassRoutePattern(
            base_classes=["APIView", "ViewSet", "GenericAPIView"],
            method_names=["get", "post", "put", "patch", "delete"],
        )
    """

    base_classes: list[str]
    method_names: list[str] = field(
        default_factory=lambda: ["get", "post", "put", "patch", "delete", "head", "options"]
    )


@dataclass
class HandlerPattern:
    """Pattern for exception handlers.

    Examples:
        # Flask: @app.errorhandler(Exception)
        HandlerPattern(decorator_pattern="*.errorhandler")

        # FastAPI decorator: @app.exception_handler(Exception)
        HandlerPattern(decorator_pattern="*.exception_handler")

        # FastAPI call: app.add_exception_handler(Exception, handler)
        HandlerPattern(call_pattern="*.add_exception_handler")
    """

    decorator_pattern: str | None = None
    call_pattern: str | None = None
    exception_arg: str = "arg[0]"

    def matches_decorator(self, decorator_name: str) -> bool:
        """Check if this pattern matches a decorator name."""
        if not self.decorator_pattern:
            return False
        return fnmatch(decorator_name, self.decorator_pattern)

    def matches_call(self, call_name: str) -> bool:
        """Check if this pattern matches a function call name."""
        if not self.call_pattern:
            return False
        return fnmatch(call_name, self.call_pattern)


@dataclass
class FrameworkConfig:
    """Complete configuration for a framework."""

    name: str
    route_patterns: list[DecoratorRoutePattern] = field(default_factory=list)
    class_patterns: list[ClassRoutePattern] = field(default_factory=list)
    handler_patterns: list[HandlerPattern] = field(default_factory=list)
    handled_exceptions: list[str] = field(default_factory=list)
