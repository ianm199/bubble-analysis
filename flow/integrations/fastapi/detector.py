"""FastAPI route and exception handler detection."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from flow.enums import EntrypointKind, Framework
from flow.integrations.base import Entrypoint, GlobalHandler


class FastAPIRouteVisitor(cst.CSTVisitor):
    """Detects FastAPI route decorators (@router.get, @router.post, etc.)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}

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
                        kind=EntrypointKind.HTTP_ROUTE,
                        metadata={
                            "http_method": route_info["method"],
                            "http_path": route_info["path"],
                            "framework": Framework.FASTAPI,
                        },
                    )
                )
        return True

    def _parse_route_decorator(self, decorator: cst.Decorator) -> dict[str, str] | None:
        if not isinstance(decorator.decorator, cst.Call):
            return None

        call = decorator.decorator

        if not isinstance(call.func, cst.Attribute):
            return None

        method_name = call.func.attr.value.lower()
        if method_name not in self.HTTP_METHODS:
            return None

        path = None
        if call.args:
            first_arg = call.args[0]
            if isinstance(first_arg.value, cst.SimpleString):
                path = first_arg.value.evaluated_value

        if path:
            return {"path": path, "method": method_name.upper()}
        return None


class FastAPIExceptionHandlerVisitor(cst.CSTVisitor):
    """Detects FastAPI exception handlers.

    Detects both patterns:
    - app.add_exception_handler(ExceptionType, handler_func)
    - @app.exception_handler(ExceptionType) decorator
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.handlers: list[GlobalHandler] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            handler_info = self._parse_exception_handler_decorator(decorator)
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

    def _parse_exception_handler_decorator(self, decorator: cst.Decorator) -> str | None:
        if not isinstance(decorator.decorator, cst.Call):
            return None

        call = decorator.decorator
        if not isinstance(call.func, cst.Attribute):
            return None

        if call.func.attr.value != "exception_handler":
            return None

        if not call.args:
            return None

        return self._get_name_from_expr(call.args[0].value)

    def visit_Call(self, node: cst.Call) -> bool:
        if not isinstance(node.func, cst.Attribute):
            return True
        if node.func.attr.value != "add_exception_handler":
            return True
        if len(node.args) < 2:
            return True

        exception_type = self._get_name_from_expr(node.args[0].value)
        handler_name = self._get_name_from_expr(node.args[1].value)

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

    def _get_name_from_expr(self, expr: cst.BaseExpression) -> str:
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            base = self._get_name_from_expr(expr.value)
            if base:
                return f"{base}.{expr.attr.value}"
            return expr.attr.value
        return ""


def detect_fastapi_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect FastAPI route entrypoints in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = FastAPIRouteVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.entrypoints
    except Exception:
        return []


def detect_fastapi_global_handlers(source: str, file_path: str) -> list[GlobalHandler]:
    """Detect FastAPI exception handlers in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = FastAPIExceptionHandlerVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.handlers
    except Exception:
        return []
