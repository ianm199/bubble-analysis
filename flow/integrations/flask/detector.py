"""Flask route and error handler detection."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from flow.integrations.base import Entrypoint, GlobalHandler


class FlaskRouteVisitor(cst.CSTVisitor):
    """Detects Flask route decorators (@app.route, @blueprint.route)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

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
                        kind="http_route",
                        metadata={
                            "http_method": route_info["method"],
                            "http_path": route_info["path"],
                            "framework": "flask",
                        },
                    )
                )
        return True

    def _parse_route_decorator(self, decorator: cst.Decorator) -> dict[str, str] | None:
        if not isinstance(decorator.decorator, cst.Call):
            return None

        call = decorator.decorator

        if isinstance(call.func, cst.Attribute):
            if call.func.attr.value != "route":
                return None
        elif isinstance(call.func, cst.Name):
            if call.func.value != "route":
                return None
        else:
            return None

        path = None
        if call.args:
            first_arg = call.args[0]
            if isinstance(first_arg.value, cst.SimpleString):
                path = first_arg.value.evaluated_value
            elif isinstance(first_arg.value, cst.ConcatenatedString):
                parts = []
                for part in first_arg.value.left, first_arg.value.right:
                    if isinstance(part, cst.SimpleString):
                        parts.append(part.evaluated_value)
                path = "".join(parts) if parts else None

        methods = ["GET"]
        for arg in call.args:
            if arg.keyword and arg.keyword.value == "methods":
                if isinstance(arg.value, cst.List):
                    methods = []
                    for el in arg.value.elements:
                        if isinstance(el.value, cst.SimpleString):
                            methods.append(el.value.evaluated_value)

        if path:
            return {"path": path, "method": methods[0] if methods else "GET"}
        return None


class FlaskErrorHandlerVisitor(cst.CSTVisitor):
    """Detects Flask error handlers (@app.errorhandler, @blueprint.errorhandler)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.handlers: list[GlobalHandler] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            handler_info = self._parse_errorhandler_decorator(decorator)
            if handler_info:
                pos = self.get_metadata(PositionProvider, node)
                self.handlers.append(
                    GlobalHandler(
                        file=self.file_path,
                        line=pos.start.line,
                        function=node.name.value,
                        handled_type=handler_info["exception_type"],
                    )
                )
        return True

    def _parse_errorhandler_decorator(self, decorator: cst.Decorator) -> dict[str, str] | None:
        if not isinstance(decorator.decorator, cst.Call):
            return None

        call = decorator.decorator

        if isinstance(call.func, cst.Attribute):
            if call.func.attr.value != "errorhandler":
                return None
        elif isinstance(call.func, cst.Name):
            if call.func.value != "errorhandler":
                return None
        else:
            return None

        if not call.args:
            return None

        first_arg = call.args[0].value
        exception_type = self._get_name_from_expr(first_arg)
        if exception_type:
            return {"exception_type": exception_type}
        return None

    def _get_name_from_expr(self, expr: cst.BaseExpression) -> str:
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            base = self._get_name_from_expr(expr.value)
            if base:
                return f"{base}.{expr.attr.value}"
            return expr.attr.value
        return ""


def detect_flask_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect Flask route entrypoints in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = FlaskRouteVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.entrypoints
    except Exception:
        return []


def detect_flask_global_handlers(source: str, file_path: str) -> list[GlobalHandler]:
    """Detect Flask error handlers in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = FlaskErrorHandlerVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.handlers
    except Exception:
        return []
