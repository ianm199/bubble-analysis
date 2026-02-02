"""Datasette plugin route detector.

Detects HTTP routes from Datasette plugin hooks that return route tuples.

Pattern detected:
    @hookimpl
    def register_routes():
        return [
            (r"^/-/api$", api_handler),
            (r"^/-/sql$", sql_handler),
        ]

The entrypoints are `api_handler` and `sql_handler`, not `register_routes`.

Usage:
    Copy this file to your project's .flow/detectors/ directory.
    It will be automatically loaded when running bubble commands.
"""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind
from bubble.integrations.base import Entrypoint


class DatasetteRouteVisitor(cst.CSTVisitor):
    """Visitor that extracts routes from register_routes() return values."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []
        self.function_lines: dict[str, int] = {}
        self._in_register_routes = False

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        pos = self.get_metadata(PositionProvider, node)
        self.function_lines[node.name.value] = pos.start.line

        if node.name.value == "register_routes":
            for dec in node.decorators:
                if self._is_hookimpl(dec):
                    self._in_register_routes = True
                    break
        return True

    def leave_FunctionDef(self, node: cst.FunctionDef) -> None:
        if node.name.value == "register_routes":
            self._in_register_routes = False

    def visit_Return(self, node: cst.Return) -> bool:
        if not self._in_register_routes or node.value is None:
            return True

        if isinstance(node.value, cst.List):
            for el in node.value.elements:
                self._extract_route_tuple(el)

        return True

    def _extract_route_tuple(self, element: cst.BaseElement) -> None:
        """Extract (path, handler) from a tuple element."""
        if not isinstance(element, cst.Element):
            return
        if not isinstance(element.value, cst.Tuple):
            return

        tuple_els = list(element.value.elements)
        if len(tuple_els) < 2:
            return

        path = self._get_string(tuple_els[0])
        handler = self._get_name(tuple_els[1])

        if path and handler:
            line = self.function_lines.get(handler, 1)
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function=handler,
                    line=line,
                    kind=EntrypointKind.HTTP_ROUTE,
                    metadata={
                        "http_path": path,
                        "http_method": "GET",
                        "framework": "datasette",
                    },
                )
            )

    def _is_hookimpl(self, dec: cst.Decorator) -> bool:
        """Check if decorator is @hookimpl."""
        if isinstance(dec.decorator, cst.Name):
            return dec.decorator.value == "hookimpl"
        if isinstance(dec.decorator, cst.Call):
            if isinstance(dec.decorator.func, cst.Name):
                return dec.decorator.func.value == "hookimpl"
        return False

    def _get_string(self, el: cst.BaseElement) -> str | None:
        """Extract string value from a tuple element."""
        if isinstance(el, cst.Element) and isinstance(el.value, cst.SimpleString):
            return el.value.evaluated_value
        return None

    def _get_name(self, el: cst.BaseElement) -> str | None:
        """Extract function name from a tuple element."""
        if isinstance(el, cst.Element) and isinstance(el.value, cst.Name):
            return el.value.value
        return None


class DatasetteRouteDetector:
    """Custom detector for Datasette plugin routes.

    Implements the EntrypointDetector protocol.
    """

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect Datasette routes in a Python source file."""
        try:
            module = cst.parse_module(source)
        except Exception:
            return []

        wrapper = MetadataWrapper(module)
        visitor = DatasetteRouteVisitor(file_path)

        try:
            wrapper.visit(visitor)
            return visitor.entrypoints
        except Exception:
            return []
