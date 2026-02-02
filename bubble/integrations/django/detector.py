"""Django and Django REST Framework route detection."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.integrations.base import Entrypoint, GlobalHandler

DRF_BASE_CLASSES = {
    "APIView",
    "ViewSet",
    "ModelViewSet",
    "ReadOnlyModelViewSet",
    "GenericAPIView",
    "GenericViewSet",
    "ListAPIView",
    "CreateAPIView",
    "RetrieveAPIView",
    "UpdateAPIView",
    "DestroyAPIView",
    "ListCreateAPIView",
    "RetrieveUpdateAPIView",
    "RetrieveDestroyAPIView",
    "RetrieveUpdateDestroyAPIView",
}

DRF_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
DRF_ACTION_METHODS = {"list", "create", "retrieve", "update", "partial_update", "destroy"}
DRF_METHOD_TO_HTTP = {
    "list": "GET",
    "create": "POST",
    "retrieve": "GET",
    "update": "PUT",
    "partial_update": "PATCH",
    "destroy": "DELETE",
}

DRF_GENERICS_QUALIFIERS = {
    "generics",
    "rest_framework.generics",
    "viewsets",
    "rest_framework.viewsets",
}

DJANGO_VIEW_BASE_CLASSES = {
    "View",
    "TemplateView",
    "RedirectView",
    "FormView",
    "DetailView",
    "ListView",
}


class DjangoViewVisitor(cst.CSTVisitor):
    """Detects Django and DRF view classes."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []
        self._in_class: str | None = None
        self._class_is_view = False
        self._class_line: int = 0
        self._class_methods: dict[str, int] = {}

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._in_class = node.name.value
        self._class_is_view = self._is_view_class(node)
        self._class_methods = {}
        if self._class_is_view:
            pos = self.get_metadata(PositionProvider, node)
            self._class_line = pos.start.line
        return True

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        if self._class_is_view and self._in_class:
            method_name = node.name.value.lower()
            if method_name in DRF_HTTP_METHODS or method_name in DRF_ACTION_METHODS:
                pos = self.get_metadata(PositionProvider, node)
                self._class_methods[method_name] = pos.start.line
        return True

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        if self._class_is_view and self._in_class:
            class_name = self._in_class
            if self._class_methods:
                for method_name, line in self._class_methods.items():
                    http_method = DRF_METHOD_TO_HTTP.get(method_name, method_name.upper())
                    self.entrypoints.append(
                        Entrypoint(
                            file=self.file_path,
                            function=f"{class_name}.{method_name}",
                            line=line,
                            kind="http_route",
                            metadata={
                                "framework": "django",
                                "view_type": "class",
                                "http_method": http_method,
                                "http_path": f"<drf:{class_name}>",
                            },
                        )
                    )
            else:
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=class_name,
                        line=self._class_line,
                        kind="http_route",
                        metadata={
                            "framework": "django",
                            "view_type": "class",
                            "http_method": "ANY",
                            "http_path": f"<drf:{class_name}>",
                        },
                    )
                )

        self._in_class = None
        self._class_is_view = False
        self._class_line = 0
        self._class_methods = {}

    def _is_view_class(self, node: cst.ClassDef) -> bool:
        """Check if a class inherits from a Django/DRF view base class."""
        for base in node.bases:
            base_name = self._get_base_class_name(base.value)
            if base_name:
                simple_name = base_name.split(".")[-1]
                if simple_name in DRF_BASE_CLASSES or simple_name in DJANGO_VIEW_BASE_CLASSES:
                    return True
                for qualifier in DRF_GENERICS_QUALIFIERS:
                    if base_name.startswith(qualifier + "."):
                        return True
        return False

    def _get_base_class_name(self, expr: cst.BaseExpression) -> str:
        """Extract the full name from a base class expression."""
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            base = self._get_base_class_name(expr.value)
            if base:
                return f"{base}.{expr.attr.value}"
            return expr.attr.value
        elif isinstance(expr, cst.Subscript):
            return self._get_base_class_name(expr.value)
        return ""


class DjangoFunctionViewVisitor(cst.CSTVisitor):
    """Detects Django function-based views with @api_view decorator."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            if self._is_api_view_decorator(decorator):
                pos = self.get_metadata(PositionProvider, node)
                methods = self._extract_methods(decorator)
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=node.name.value,
                        line=pos.start.line,
                        kind="http_route",
                        metadata={
                            "framework": "django",
                            "view_type": "function",
                            "http_method": methods[0] if methods else "GET",
                        },
                    )
                )
                break
        return True

    def _is_api_view_decorator(self, decorator: cst.Decorator) -> bool:
        """Check if decorator is @api_view."""
        dec = decorator.decorator
        if isinstance(dec, cst.Call):
            if isinstance(dec.func, cst.Name) and dec.func.value == "api_view":
                return True
            if isinstance(dec.func, cst.Attribute) and dec.func.attr.value == "api_view":
                return True
        elif isinstance(dec, cst.Name) and dec.value == "api_view":
            return True
        return False

    def _extract_methods(self, decorator: cst.Decorator) -> list[str]:
        """Extract HTTP methods from @api_view(['GET', 'POST'])."""
        methods: list[str] = []
        dec = decorator.decorator
        if isinstance(dec, cst.Call) and dec.args:
            first_arg = dec.args[0].value
            if isinstance(first_arg, cst.List):
                for el in first_arg.elements:
                    if isinstance(el, cst.Element) and isinstance(el.value, cst.SimpleString):
                        methods.append(el.value.evaluated_value or "")
        return methods if methods else ["GET"]


class DjangoURLPatternVisitor(cst.CSTVisitor):
    """Detects Django URL patterns to extract route paths."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.url_patterns: list[dict[str, str]] = []

    def visit_Call(self, node: cst.Call) -> bool:
        func_name = self._get_func_name(node.func)
        if func_name in ("path", "re_path", "url"):
            pattern = self._extract_url_info(node)
            if pattern:
                self.url_patterns.append(pattern)
        return True

    def _get_func_name(self, expr: cst.BaseExpression) -> str:
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            return expr.attr.value
        return ""

    def _extract_url_info(self, call: cst.Call) -> dict[str, str] | None:
        """Extract URL path and view from path() or re_path() call."""
        if len(call.args) < 2:
            return None

        path_arg = call.args[0].value
        view_arg = call.args[1].value

        path_str = self._extract_string(path_arg)
        view_name = self._extract_view_name(view_arg)

        if path_str is not None and view_name:
            return {"path": path_str, "view": view_name}
        return None

    def _extract_string(self, expr: cst.BaseExpression) -> str | None:
        if isinstance(expr, cst.SimpleString):
            return expr.evaluated_value
        elif isinstance(expr, cst.ConcatenatedString):
            parts = []
            for part in [expr.left, expr.right]:
                if isinstance(part, cst.SimpleString):
                    val = part.evaluated_value
                    if val:
                        parts.append(val)
            return "".join(parts) if parts else None
        return None

    def _extract_view_name(self, expr: cst.BaseExpression) -> str:
        """Extract view name from the second argument of path()."""
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            return f"{self._extract_view_name(expr.value)}.{expr.attr.value}"
        elif isinstance(expr, cst.Call):
            if isinstance(expr.func, cst.Attribute) and expr.func.attr.value == "as_view":
                return self._extract_view_name(expr.func.value)
        return ""


class DjangoExceptionHandlerVisitor(cst.CSTVisitor):
    """Detects Django REST Framework exception handlers."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.handlers: list[GlobalHandler] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        for decorator in node.decorators:
            handler_type = self._is_exception_handler(decorator)
            if handler_type:
                pos = self.get_metadata(PositionProvider, node)
                self.handlers.append(
                    GlobalHandler(
                        file=self.file_path,
                        line=pos.start.line,
                        function=node.name.value,
                        handled_type=handler_type,
                    )
                )
        return True

    def _is_exception_handler(self, decorator: cst.Decorator) -> str | None:
        """Check if decorator is @exception_handler or similar."""
        dec = decorator.decorator
        if isinstance(dec, cst.Call):
            func_name = self._get_name(dec.func)
            if func_name in ("exception_handler", "api_exception_handler"):
                if dec.args:
                    return self._get_name(dec.args[0].value)
                return "Exception"
        elif isinstance(dec, cst.Name):
            if dec.value == "exception_handler":
                return "Exception"
        return None

    def _get_name(self, expr: cst.BaseExpression) -> str:
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            return f"{self._get_name(expr.value)}.{expr.attr.value}"
        return ""


def detect_django_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect Django view entrypoints in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    entrypoints: list[Entrypoint] = []

    wrapper = MetadataWrapper(module)
    class_visitor = DjangoViewVisitor(file_path)
    try:
        wrapper.visit(class_visitor)
        entrypoints.extend(class_visitor.entrypoints)
    except Exception:
        pass

    wrapper = MetadataWrapper(module)
    func_visitor = DjangoFunctionViewVisitor(file_path)
    try:
        wrapper.visit(func_visitor)
        entrypoints.extend(func_visitor.entrypoints)
    except Exception:
        pass

    return entrypoints


def detect_django_global_handlers(source: str, file_path: str) -> list[GlobalHandler]:
    """Detect Django exception handlers in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = DjangoExceptionHandlerVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.handlers
    except Exception:
        return []


def detect_django_url_patterns(source: str, file_path: str) -> list[dict[str, str]]:
    """Detect Django URL patterns in a urls.py file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = DjangoURLPatternVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.url_patterns
    except Exception:
        return []
