"""Framework detectors for identifying entrypoints and patterns."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from flow.models import Entrypoint, GlobalHandler

FRAMEWORK_EXCEPTION_RESPONSES: dict[str, dict[str, str]] = {
    "fastapi": {
        "fastapi.HTTPException": "HTTP {status_code}",
        "HTTPException": "HTTP {status_code}",
        "starlette.exceptions.HTTPException": "HTTP {status_code}",
        "pydantic.ValidationError": "HTTP 422",
        "pydantic_core.ValidationError": "HTTP 422",
        "ValidationError": "HTTP 422",
        "RequestValidationError": "HTTP 422",
    },
    "flask": {
        "werkzeug.exceptions.HTTPException": "HTTP {code}",
        "HTTPException": "HTTP {code}",
        "werkzeug.exceptions.NotFound": "HTTP 404",
        "NotFound": "HTTP 404",
        "werkzeug.exceptions.BadRequest": "HTTP 400",
        "BadRequest": "HTTP 400",
        "werkzeug.exceptions.Unauthorized": "HTTP 401",
        "Unauthorized": "HTTP 401",
        "werkzeug.exceptions.Forbidden": "HTTP 403",
        "Forbidden": "HTTP 403",
        "werkzeug.exceptions.InternalServerError": "HTTP 500",
        "InternalServerError": "HTTP 500",
    },
}


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
                        kind="http_route",
                        metadata={
                            "http_method": route_info["method"],
                            "http_path": route_info["path"],
                            "framework": "fastapi",
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


class CLIEntrypointVisitor(cst.CSTVisitor):
    """Detects CLI entrypoints (if __name__ == '__main__': blocks)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    IGNORED_FUNCTIONS = {
        "print", "exit", "quit", "help", "input",
        "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
        "open", "close", "read", "write",
        "format", "repr", "type", "isinstance", "hasattr", "getattr", "setattr",
    }

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_If(self, node: cst.If) -> bool:
        if not self._is_main_guard(node.test):
            return True

        pos = self.get_metadata(PositionProvider, node)
        called_functions = self._extract_called_functions(node.body)

        if called_functions:
            for func_name in called_functions:
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=func_name,
                        line=pos.start.line,
                        kind="cli_script",
                        metadata={
                            "guard_line": pos.start.line,
                            "framework": "cli",
                        },
                    )
                )
        else:
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function="<main_block>",
                    line=pos.start.line,
                    kind="cli_script",
                    metadata={
                        "guard_line": pos.start.line,
                        "framework": "cli",
                        "inline": True,
                    },
                )
            )

        return False

    def _is_main_guard(self, test: cst.BaseExpression) -> bool:
        if not isinstance(test, cst.Comparison):
            return False

        if not isinstance(test.left, cst.Name):
            return False
        if test.left.value != "__name__":
            return False

        if len(test.comparisons) != 1:
            return False

        comp = test.comparisons[0]
        if not isinstance(comp.operator, cst.Equal):
            return False

        if isinstance(comp.comparator, cst.SimpleString):
            value = comp.comparator.evaluated_value
            return value == "__main__"

        return False

    def _extract_called_functions(self, body: cst.BaseSuite) -> list[str]:
        functions: list[str] = []
        seen: set[str] = set()

        if isinstance(body, cst.IndentedBlock):
            for stmt in body.body:
                if isinstance(stmt, cst.SimpleStatementLine):
                    for item in stmt.body:
                        if isinstance(item, cst.Expr) and isinstance(item.value, cst.Call):
                            func_name = self._get_call_name(item.value)
                            if func_name and func_name not in self.IGNORED_FUNCTIONS and func_name not in seen:
                                functions.append(func_name)
                                seen.add(func_name)

        return functions

    def _get_call_name(self, call: cst.Call) -> str:
        if isinstance(call.func, cst.Name):
            return call.func.value
        elif isinstance(call.func, cst.Attribute):
            return call.func.attr.value
        return ""


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


class FastAPIExceptionHandlerVisitor(cst.CSTVisitor):
    """Detects FastAPI exception handlers (app.add_exception_handler calls)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.handlers: list[GlobalHandler] = []

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


def detect_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect entrypoints in a Python source file (HTTP routes and CLI scripts)."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    entrypoints: list[Entrypoint] = []

    flask_visitor = FlaskRouteVisitor(file_path)
    try:
        wrapper.visit(flask_visitor)
        entrypoints.extend(flask_visitor.entrypoints)
    except Exception:
        pass

    fastapi_visitor = FastAPIRouteVisitor(file_path)
    try:
        wrapper.visit(fastapi_visitor)
        entrypoints.extend(fastapi_visitor.entrypoints)
    except Exception:
        pass

    cli_visitor = CLIEntrypointVisitor(file_path)
    try:
        wrapper.visit(cli_visitor)
        entrypoints.extend(cli_visitor.entrypoints)
    except Exception:
        pass

    return entrypoints


def detect_global_handlers(source: str, file_path: str) -> list[GlobalHandler]:
    """Detect global exception handlers in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    handlers: list[GlobalHandler] = []

    flask_visitor = FlaskErrorHandlerVisitor(file_path)
    try:
        wrapper.visit(flask_visitor)
        handlers.extend(flask_visitor.handlers)
    except Exception:
        pass

    fastapi_visitor = FastAPIExceptionHandlerVisitor(file_path)
    try:
        wrapper.visit(fastapi_visitor)
        handlers.extend(fastapi_visitor.handlers)
    except Exception:
        pass

    return handlers
