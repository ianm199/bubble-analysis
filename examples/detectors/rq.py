"""RQ (Redis Queue) job detector.

Detects RQ jobs as entrypoints since they're triggered externally by workers.

Patterns detected:
    @job
    def send_email(to, subject):
        ...

    @job('high')
    def process_payment(order_id):
        ...

    queue.enqueue(send_notification, user_id, message)

Usage:
    Copy this file to your project's .flow/detectors/ directory.
    It will be automatically loaded when running bubble commands.
"""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind
from bubble.integrations.base import Entrypoint


class RQJobVisitor(cst.CSTVisitor):
    """Visitor that detects RQ job decorators and enqueue calls."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []
        self._seen_functions: set[str] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        if self._has_job_decorator(node):
            pos = self.get_metadata(PositionProvider, node)
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function=node.name.value,
                    line=pos.start.line,
                    kind=EntrypointKind.QUEUE_HANDLER,
                    metadata={"framework": "rq"},
                )
            )
            self._seen_functions.add(node.name.value)
        return True

    def visit_Call(self, node: cst.Call) -> bool:
        """Detect queue.enqueue(func, ...) calls."""
        if not isinstance(node.func, cst.Attribute):
            return True

        method_name = node.func.attr.value
        if method_name not in ("enqueue", "enqueue_call", "enqueue_at", "enqueue_in"):
            return True

        if not node.args:
            return True

        first_arg = node.args[0].value
        if not isinstance(first_arg, cst.Name):
            return True

        func_name = first_arg.value
        if func_name in self._seen_functions:
            return True

        pos = self.get_metadata(PositionProvider, node)
        self.entrypoints.append(
            Entrypoint(
                file=self.file_path,
                function=func_name,
                line=pos.start.line,
                kind=EntrypointKind.QUEUE_HANDLER,
                metadata={
                    "framework": "rq",
                    "enqueue_method": method_name,
                },
            )
        )
        self._seen_functions.add(func_name)

        return True

    def _has_job_decorator(self, node: cst.FunctionDef) -> bool:
        """Check if function has @job decorator."""
        for decorator in node.decorators:
            dec = decorator.decorator

            if isinstance(dec, cst.Name) and dec.value == "job":
                return True

            if isinstance(dec, cst.Call):
                if isinstance(dec.func, cst.Name) and dec.func.value == "job":
                    return True

        return False


class RQJobDetector:
    """Custom detector for RQ (Redis Queue) jobs.

    Implements the EntrypointDetector protocol.
    """

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect RQ jobs in a Python source file."""
        try:
            module = cst.parse_module(source)
        except Exception:
            return []

        wrapper = MetadataWrapper(module)
        visitor = RQJobVisitor(file_path)

        try:
            wrapper.visit(visitor)
            return visitor.entrypoints
        except Exception:
            return []
