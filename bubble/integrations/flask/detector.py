"""Flask route and error handler detection."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind, Framework
from bubble.integrations.base import Entrypoint, GlobalHandler

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


class FlaskRouteVisitor(cst.CSTVisitor):
    """
    Detects Flask route decorators.

    Supports:
    - @app.route, @blueprint.route (standard Flask)
    - @expose (Flask-AppBuilder)
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    ROUTE_DECORATOR_NAMES = {"route", "expose"}

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
                            "framework": Framework.FLASK,
                        },
                    )
                )
        return True

    def _parse_route_decorator(self, decorator: cst.Decorator) -> dict[str, str] | None:
        if not isinstance(decorator.decorator, cst.Call):
            return None

        call = decorator.decorator

        if isinstance(call.func, cst.Attribute):
            if call.func.attr.value not in self.ROUTE_DECORATOR_NAMES:
                return None
        elif isinstance(call.func, cst.Name):
            if call.func.value not in self.ROUTE_DECORATOR_NAMES:
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
                methods = self._extract_methods(arg.value)

        if path:
            return {"path": path, "method": methods[0] if methods else "GET"}
        return None

    def _extract_methods(self, value: cst.BaseExpression) -> list[str]:
        """
        Extract HTTP methods from a list or tuple.

        Handles both Flask-style lists and Flask-AppBuilder-style tuples:
        - methods=["GET", "POST"]
        - methods=("GET", "POST")
        """
        methods: list[str] = []
        if isinstance(value, cst.List | cst.Tuple):
            for el in value.elements:
                if isinstance(el, cst.Element) and isinstance(el.value, cst.SimpleString):
                    extracted = el.value.evaluated_value
                    if extracted:
                        methods.append(extracted)
        return methods if methods else ["GET"]


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


class FlaskRESTfulVisitor(cst.CSTVisitor):
    """
    Detects Flask-RESTful Resource classes and add_resource() registrations.

    Supports:
    - api.add_resource(ResourceClass, "/path")
    - api.add_resource(ResourceClass, "/path1", "/path2")
    - Custom methods like api.add_org_resource()
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    ADD_RESOURCE_METHODS = {"add_resource", "add_org_resource"}

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []
        self.resource_classes: dict[str, dict[str, int]] = {}
        self.resource_registrations: list[tuple[str, list[str], int]] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        methods_found: dict[str, int] = {}
        for item in node.body.body:
            if isinstance(item, cst.FunctionDef):
                method_name = item.name.value.lower()
                if method_name in HTTP_METHODS and not self._has_route_decorator(item):
                    pos = self.get_metadata(PositionProvider, item)
                    methods_found[method_name.upper()] = pos.start.line

        if methods_found:
            self.resource_classes[node.name.value] = methods_found

        return True

    def _has_route_decorator(self, node: cst.FunctionDef) -> bool:
        """Check if a function has a route decorator like @expose, @route."""
        for decorator in node.decorators:
            dec = decorator.decorator
            if isinstance(dec, cst.Call):
                if isinstance(dec.func, cst.Attribute):
                    if dec.func.attr.value in ("route", "expose"):
                        return True
                elif isinstance(dec.func, cst.Name):
                    if dec.func.value in ("route", "expose"):
                        return True
            elif isinstance(dec, cst.Attribute):
                if dec.attr.value in ("route", "expose"):
                    return True
            elif isinstance(dec, cst.Name):
                if dec.value in ("route", "expose"):
                    return True
        return False

    def visit_Call(self, node: cst.Call) -> bool:
        if not isinstance(node.func, cst.Attribute):
            return True

        method_name = node.func.attr.value
        if method_name not in self.ADD_RESOURCE_METHODS:
            return True

        if len(node.args) < 2:
            return True

        first_arg = node.args[0].value
        resource_name = self._get_name_from_expr(first_arg)
        if not resource_name:
            return True

        urls: list[str] = []
        for arg in node.args[1:]:
            if arg.keyword is not None:
                continue
            url = self._extract_string(arg.value)
            if url:
                urls.append(url)

        if urls:
            pos = self.get_metadata(PositionProvider, node)
            self.resource_registrations.append((resource_name, urls, pos.start.line))

        return True

    def leave_Module(self, original_node: cst.Module) -> None:
        registered_classes: set[str] = set()

        for resource_name, urls, reg_line in self.resource_registrations:
            registered_classes.add(resource_name)
            methods = self.resource_classes.get(resource_name, {})
            if not methods:
                methods = {"GET": reg_line}

            for url in urls:
                for method, method_line in methods.items():
                    self.entrypoints.append(
                        Entrypoint(
                            file=self.file_path,
                            function=f"{resource_name}.{method.lower()}",
                            line=method_line,
                            kind=EntrypointKind.HTTP_ROUTE,
                            metadata={
                                "http_method": method,
                                "http_path": url,
                                "framework": Framework.FLASK,
                                "flask_restful": "true",
                            },
                        )
                    )

        for class_name, methods in self.resource_classes.items():
            if class_name in registered_classes:
                continue

            for method, method_line in methods.items():
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=f"{class_name}.{method.lower()}",
                        line=method_line,
                        kind=EntrypointKind.HTTP_ROUTE,
                        metadata={
                            "http_method": method,
                            "http_path": f"<flask-restful:{class_name}>",
                            "framework": Framework.FLASK,
                            "flask_restful": "true",
                        },
                    )
                )

    def _get_name_from_expr(self, expr: cst.BaseExpression) -> str:
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            return expr.attr.value
        return ""

    def _extract_string(self, node: cst.BaseExpression) -> str | None:
        if isinstance(node, cst.SimpleString):
            return node.evaluated_value
        elif isinstance(node, cst.ConcatenatedString):
            parts = []
            for part in (node.left, node.right):
                if isinstance(part, cst.SimpleString):
                    val = part.evaluated_value
                    if val:
                        parts.append(val)
            return "".join(parts) if parts else None
        return None


def detect_flask_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect Flask route entrypoints in a Python source file.

    Detects both decorator-based routes (@app.route) and
    Flask-RESTful call-based routes (api.add_resource).
    """
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    entrypoints: list[Entrypoint] = []
    wrapper = MetadataWrapper(module)

    route_visitor = FlaskRouteVisitor(file_path)
    try:
        wrapper.visit(route_visitor)
        entrypoints.extend(route_visitor.entrypoints)
    except Exception:
        pass

    restful_visitor = FlaskRESTfulVisitor(file_path)
    try:
        wrapper.visit(restful_visitor)
        entrypoints.extend(restful_visitor.entrypoints)
    except Exception:
        pass

    return entrypoints


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


def correlate_flask_restful_entrypoints(entrypoints: list[Entrypoint]) -> list[Entrypoint]:
    """Correlate Flask-RESTful entrypoints across files.

    Flask-RESTful apps often define Resource classes in one file and register
    them with api.add_resource() in another. This function merges information
    from both sources:
    - Class definitions have correct methods but placeholder paths
    - Registrations have correct paths but fallback methods

    Same-file cases (already fully resolved) are passed through unchanged.
    Only placeholder entries trigger cross-file correlation.

    Returns a new list with correlated entrypoints.
    """
    placeholder_classes: dict[str, list[Entrypoint]] = {}
    real_path_entries: dict[str, list[Entrypoint]] = {}
    non_flask_restful: list[Entrypoint] = []

    for ep in entrypoints:
        if not ep.metadata.get("flask_restful"):
            non_flask_restful.append(ep)
            continue

        path = ep.metadata.get("http_path", "")

        if path.startswith("<flask-restful:") and path.endswith(">"):
            class_name = path[15:-1]
            if class_name not in placeholder_classes:
                placeholder_classes[class_name] = []
            placeholder_classes[class_name].append(ep)
        else:
            parts = ep.function.rsplit(".", 1)
            if len(parts) == 2:
                class_name = parts[0]
                if class_name not in real_path_entries:
                    real_path_entries[class_name] = []
                real_path_entries[class_name].append(ep)
            else:
                non_flask_restful.append(ep)

    result: list[Entrypoint] = list(non_flask_restful)

    for class_name, class_eps in placeholder_classes.items():
        if class_name in real_path_entries:
            reg_eps = real_path_entries[class_name]
            paths_from_registrations = list({ep.metadata.get("http_path", "") for ep in reg_eps})

            for class_ep in class_eps:
                for reg_path in paths_from_registrations:
                    result.append(
                        Entrypoint(
                            file=class_ep.file,
                            function=class_ep.function,
                            line=class_ep.line,
                            kind=class_ep.kind,
                            metadata={
                                **class_ep.metadata,
                                "http_path": reg_path,
                            },
                        )
                    )

            del real_path_entries[class_name]
        else:
            result.extend(class_eps)

    for _class_name, eps in real_path_entries.items():
        result.extend(eps)

    return result
