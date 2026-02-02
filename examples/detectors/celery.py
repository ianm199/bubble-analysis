"""Celery task detector.

Detects Celery tasks as entrypoints since they're triggered externally.

Patterns detected:
    @app.task
    def send_email(to, subject, body):
        ...

    @shared_task
    def process_payment(order_id):
        ...

    @celery.task(bind=True)
    def retry_operation(self, data):
        ...

Usage:
    Copy this file to your project's .flow/detectors/ directory.
    It will be automatically loaded when running bubble commands.
"""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind
from bubble.integrations.base import Entrypoint


CELERY_DECORATORS = {"task", "shared_task"}


class CeleryTaskVisitor(cst.CSTVisitor):
    """Visitor that detects Celery task decorators."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        task_info = self._find_task_decorator(node)
        if task_info:
            pos = self.get_metadata(PositionProvider, node)
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function=node.name.value,
                    line=pos.start.line,
                    kind=EntrypointKind.QUEUE_HANDLER,
                    metadata={
                        "framework": "celery",
                        "task_name": task_info.get("name", node.name.value),
                        "bind": task_info.get("bind", False),
                    },
                )
            )
        return True

    def _find_task_decorator(self, node: cst.FunctionDef) -> dict | None:
        """Check if function has a Celery task decorator."""
        for decorator in node.decorators:
            dec = decorator.decorator

            if isinstance(dec, cst.Call):
                decorator_name = self._get_decorator_name(dec.func)
                if decorator_name in CELERY_DECORATORS:
                    return self._extract_task_options(dec)

            elif isinstance(dec, cst.Attribute):
                if dec.attr.value in CELERY_DECORATORS:
                    return {}

            elif isinstance(dec, cst.Name):
                if dec.value in CELERY_DECORATORS:
                    return {}

        return None

    def _get_decorator_name(self, func: cst.BaseExpression) -> str:
        """Get the name from a decorator call."""
        if isinstance(func, cst.Attribute):
            return func.attr.value
        elif isinstance(func, cst.Name):
            return func.value
        return ""

    def _extract_task_options(self, call: cst.Call) -> dict:
        """Extract task options from decorator arguments."""
        options: dict = {}

        for arg in call.args:
            if arg.keyword is None:
                continue

            key = arg.keyword.value

            if key == "name" and isinstance(arg.value, cst.SimpleString):
                options["name"] = arg.value.evaluated_value

            elif key == "bind":
                if isinstance(arg.value, cst.Name):
                    options["bind"] = arg.value.value == "True"

        return options


class CeleryTaskDetector:
    """Custom detector for Celery tasks.

    Implements the EntrypointDetector protocol.
    """

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect Celery tasks in a Python source file."""
        try:
            module = cst.parse_module(source)
        except Exception:
            return []

        wrapper = MetadataWrapper(module)
        visitor = CeleryTaskVisitor(file_path)

        try:
            wrapper.visit(visitor)
            return visitor.entrypoints
        except Exception:
            return []
