"""Generic entrypoint and handler detection based on configuration."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind
from bubble.integrations.base import Entrypoint, GlobalHandler
from bubble.integrations.generic.config import (
    DecoratorRoutePattern,
    FrameworkConfig,
    HandlerPattern,
)


class GenericRouteVisitor(cst.CSTVisitor):
    """Detects routes based on configurable patterns."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str, config: FrameworkConfig) -> None:
        self.file_path = file_path
        self.config = config
        self.entrypoints: list[Entrypoint] = []
        self._current_class: str | None = None
        self._class_is_view = False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._current_class = node.name.value
        self._class_is_view = self._is_view_class(node)
        if self._class_is_view:
            pos = self.get_metadata(PositionProvider, node)
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function=node.name.value,
                    line=pos.start.line,
                    kind=EntrypointKind.HTTP_ROUTE,
                    metadata={
                        "framework": self.config.name,
                        "view_type": "class",
                    },
                )
            )
        return True

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        self._current_class = None
        self._class_is_view = False

    def _is_view_class(self, node: cst.ClassDef) -> bool:
        """Check if class inherits from a configured base class."""
        for base in node.bases:
            base_name = _get_name_from_expr(base.value)
            if base_name:
                simple_name = base_name.split(".")[-1]
                for pattern in self.config.class_patterns:
                    if simple_name in pattern.base_classes:
                        return True
        return False

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            route_info = self._parse_route_decorator(decorator)
            if route_info:
                pos = self.get_metadata(PositionProvider, node)
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=node.name.value,
                        line=pos.start.line,
                        kind=EntrypointKind.HTTP_ROUTE,
                        metadata={
                            "http_method": route_info["method"],
                            "http_path": route_info["path"],
                            "framework": self.config.name,
                        },
                    )
                )
        return True

    def _parse_route_decorator(self, decorator: cst.Decorator) -> dict[str, str] | None:
        """Parse a decorator against all route patterns."""
        dec = decorator.decorator

        if isinstance(dec, cst.Call):
            decorator_name = _get_decorator_method_name(dec.func)
        elif isinstance(dec, cst.Attribute):
            decorator_name = dec.attr.value
        elif isinstance(dec, cst.Name):
            decorator_name = dec.value
        else:
            return None

        if not decorator_name:
            return None

        for pattern in self.config.route_patterns:
            if pattern.matches_decorator(decorator_name):
                return self._extract_route_info(decorator, pattern, decorator_name)

        return None

    def _extract_route_info(
        self, decorator: cst.Decorator, pattern: DecoratorRoutePattern, decorator_name: str
    ) -> dict[str, str] | None:
        """Extract path and method from decorator based on pattern config."""
        dec = decorator.decorator
        if not isinstance(dec, cst.Call):
            return None

        path = self._extract_value(dec, pattern.path_source)
        if not path:
            return None

        method = self._extract_method(dec, pattern, decorator_name)

        return {"path": path, "method": method}

    def _extract_value(self, call: cst.Call, source: str) -> str | None:
        """Extract a value from a call based on source specification.

        Sources:
            "arg[0]" - First positional argument
            "arg[1]" - Second positional argument
            "kwarg[name]" - Keyword argument by name
        """
        if source.startswith("arg["):
            idx = int(source[4:-1])
            if len(call.args) > idx:
                arg = call.args[idx]
                if isinstance(arg.value, cst.SimpleString):
                    return arg.value.evaluated_value
                elif isinstance(arg.value, cst.ConcatenatedString):
                    return _extract_concatenated_string(arg.value)
        elif source.startswith("kwarg["):
            kwarg_name = source[6:-1]
            for arg in call.args:
                if arg.keyword and arg.keyword.value == kwarg_name:
                    if isinstance(arg.value, cst.SimpleString):
                        return arg.value.evaluated_value
        return None

    def _extract_method(
        self, call: cst.Call, pattern: DecoratorRoutePattern, decorator_name: str
    ) -> str:
        """Extract HTTP method based on pattern configuration."""
        if pattern.method_source == "decorator_name":
            return decorator_name.upper()

        if pattern.method_source.startswith("kwarg["):
            kwarg_name = pattern.method_source[6:-1]
            for arg in call.args:
                if arg.keyword and arg.keyword.value == kwarg_name:
                    methods = _extract_list_of_strings(arg.value)
                    if methods:
                        return methods[0]

        return pattern.default_method


class GenericHandlerVisitor(cst.CSTVisitor):
    """Detects exception handlers based on configurable patterns."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str, config: FrameworkConfig) -> None:
        self.file_path = file_path
        self.config = config
        self.handlers: list[GlobalHandler] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            handler_info = self._parse_handler_decorator(decorator)
            if handler_info:
                pos = self.get_metadata(PositionProvider, node)
                self.handlers.append(
                    GlobalHandler(
                        file=self.file_path,
                        line=pos.start.line,
                        function=node.name.value,
                        handled_type=handler_info,
                    )
                )
        return True

    def visit_Call(self, node: cst.Call) -> bool:
        """Detect function-call style handlers like app.add_exception_handler(...)."""
        call_name = _get_full_call_name(node.func)
        if not call_name:
            return True

        for pattern in self.config.handler_patterns:
            if pattern.matches_call(call_name):
                exception_type = self._extract_exception_type(node, pattern)
                handler_name = self._extract_handler_name(node)
                if exception_type and handler_name:
                    pos = self.get_metadata(PositionProvider, node)
                    self.handlers.append(
                        GlobalHandler(
                            file=self.file_path,
                            line=pos.start.line,
                            function=handler_name,
                            handled_type=exception_type,
                        )
                    )

        return True

    def _parse_handler_decorator(self, decorator: cst.Decorator) -> str | None:
        """Parse a decorator against all handler patterns."""
        dec = decorator.decorator
        if not isinstance(dec, cst.Call):
            return None

        decorator_name = _get_decorator_method_name(dec.func)
        if not decorator_name:
            return None

        for pattern in self.config.handler_patterns:
            if pattern.matches_decorator(decorator_name):
                return self._extract_exception_type_from_decorator(dec, pattern)

        return None

    def _extract_exception_type_from_decorator(
        self, call: cst.Call, pattern: HandlerPattern
    ) -> str | None:
        """Extract exception type from decorator call."""
        if pattern.exception_arg == "arg[0]" and call.args:
            return _get_name_from_expr(call.args[0].value)
        return None

    def _extract_exception_type(self, call: cst.Call, pattern: HandlerPattern) -> str | None:
        """Extract exception type from a handler registration call."""
        if pattern.exception_arg == "arg[0]" and len(call.args) >= 1:
            return _get_name_from_expr(call.args[0].value)
        return None

    def _extract_handler_name(self, call: cst.Call) -> str | None:
        """Extract handler function name (usually second argument)."""
        if len(call.args) >= 2:
            return _get_name_from_expr(call.args[1].value)
        return None


def _get_name_from_expr(expr: cst.BaseExpression) -> str:
    """Extract a name from an expression (handles Name, Attribute, Subscript)."""
    if isinstance(expr, cst.Name):
        return expr.value
    elif isinstance(expr, cst.Attribute):
        base = _get_name_from_expr(expr.value)
        if base:
            return f"{base}.{expr.attr.value}"
        return expr.attr.value
    elif isinstance(expr, cst.Subscript):
        return _get_name_from_expr(expr.value)
    return ""


def _get_decorator_method_name(func: cst.BaseExpression) -> str:
    """Get the method name from a decorator's function expression.

    Examples:
        @app.route -> "route"
        @router.get -> "get"
        @expose -> "expose"
    """
    if isinstance(func, cst.Attribute):
        return func.attr.value
    elif isinstance(func, cst.Name):
        return func.value
    return ""


def _get_full_call_name(func: cst.BaseExpression) -> str:
    """Get the full dotted name of a function call.

    Examples:
        app.add_exception_handler -> "app.add_exception_handler"
    """
    if isinstance(func, cst.Attribute):
        base = _get_full_call_name(func.value)
        if base:
            return f"{base}.{func.attr.value}"
        return func.attr.value
    elif isinstance(func, cst.Name):
        return func.value
    return ""


def _extract_concatenated_string(node: cst.ConcatenatedString) -> str | None:
    """Extract value from a concatenated string."""
    parts = []
    for part in [node.left, node.right]:
        if isinstance(part, cst.SimpleString):
            val = part.evaluated_value
            if val:
                parts.append(val)
    return "".join(parts) if parts else None


def _extract_list_of_strings(value: cst.BaseExpression) -> list[str]:
    """Extract a list of string values from a List or Tuple node."""
    methods: list[str] = []
    if isinstance(value, cst.List | cst.Tuple):
        for el in value.elements:
            if isinstance(el, cst.Element) and isinstance(el.value, cst.SimpleString):
                extracted = el.value.evaluated_value
                if extracted:
                    methods.append(extracted)
    return methods


def detect_entrypoints(source: str, file_path: str, config: FrameworkConfig) -> list[Entrypoint]:
    """Detect entrypoints using the generic detector with given configuration."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = GenericRouteVisitor(file_path, config)

    try:
        wrapper.visit(visitor)
        return visitor.entrypoints
    except Exception:
        return []


def detect_global_handlers(
    source: str, file_path: str, config: FrameworkConfig
) -> list[GlobalHandler]:
    """Detect global handlers using the generic detector with given configuration."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = GenericHandlerVisitor(file_path, config)

    try:
        wrapper.visit(visitor)
        return visitor.handlers
    except Exception:
        return []
