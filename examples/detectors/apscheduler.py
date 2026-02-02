"""APScheduler job detector.

Detects scheduled jobs as entrypoints since they're triggered by the scheduler.

Patterns detected:
    @scheduler.scheduled_job('cron', hour=6)
    def daily_cleanup():
        ...

    @sched.add_job('interval', minutes=5)
    def health_check():
        ...

    scheduler.add_job(process_queue, 'interval', seconds=30)

Usage:
    Copy this file to your project's .flow/detectors/ directory.
    It will be automatically loaded when running bubble commands.
"""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind
from bubble.integrations.base import Entrypoint


SCHEDULER_METHODS = {"scheduled_job", "add_job"}


class APSchedulerVisitor(cst.CSTVisitor):
    """Visitor that detects APScheduler job decorators and registrations."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        job_info = self._find_job_decorator(node)
        if job_info:
            pos = self.get_metadata(PositionProvider, node)
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function=node.name.value,
                    line=pos.start.line,
                    kind=EntrypointKind.SCHEDULED_JOB,
                    metadata={
                        "framework": "apscheduler",
                        "trigger": job_info.get("trigger", "unknown"),
                    },
                )
            )
        return True

    def visit_Call(self, node: cst.Call) -> bool:
        """Detect call-based job registration: scheduler.add_job(func, ...)."""
        if not isinstance(node.func, cst.Attribute):
            return True

        if node.func.attr.value != "add_job":
            return True

        if len(node.args) < 2:
            return True

        first_arg = node.args[0].value
        if not isinstance(first_arg, cst.Name):
            return True

        trigger = "unknown"
        if len(node.args) >= 2:
            second_arg = node.args[1].value
            if isinstance(second_arg, cst.SimpleString):
                trigger = second_arg.evaluated_value or "unknown"

        pos = self.get_metadata(PositionProvider, node)
        self.entrypoints.append(
            Entrypoint(
                file=self.file_path,
                function=first_arg.value,
                line=pos.start.line,
                kind=EntrypointKind.SCHEDULED_JOB,
                metadata={
                    "framework": "apscheduler",
                    "trigger": trigger,
                },
            )
        )

        return True

    def _find_job_decorator(self, node: cst.FunctionDef) -> dict | None:
        """Check if function has a scheduler job decorator."""
        for decorator in node.decorators:
            dec = decorator.decorator

            if isinstance(dec, cst.Call) and isinstance(dec.func, cst.Attribute):
                if dec.func.attr.value in SCHEDULER_METHODS:
                    return self._extract_job_info(dec)

        return None

    def _extract_job_info(self, call: cst.Call) -> dict:
        """Extract job info from decorator arguments."""
        info: dict = {}

        if call.args:
            first_arg = call.args[0].value
            if isinstance(first_arg, cst.SimpleString):
                info["trigger"] = first_arg.evaluated_value

        return info


class APSchedulerDetector:
    """Custom detector for APScheduler jobs.

    Implements the EntrypointDetector protocol.
    """

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect APScheduler jobs in a Python source file."""
        try:
            module = cst.parse_module(source)
        except Exception:
            return []

        wrapper = MetadataWrapper(module)
        visitor = APSchedulerVisitor(file_path)

        try:
            wrapper.visit(visitor)
            return visitor.entrypoints
        except Exception:
            return []
