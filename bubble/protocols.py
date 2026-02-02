"""Detector protocol definitions for custom detectors.

These protocols define the interface that custom detectors must implement.
Claude (or humans) can implement these for project-specific patterns.

Example usage in .flow/detectors/entrypoints.py:

    from bubble.protocols import EntrypointDetector
    from bubble.models import Entrypoint
    import libcst as cst

    class CeleryTaskDetector(EntrypointDetector):
        def detect(self, source: str, file_path: str) -> list[Entrypoint]:
            # Detect @celery.task decorators
            ...
"""

from typing import Protocol

from bubble.integrations.base import Entrypoint, GlobalHandler


class EntrypointDetector(Protocol):
    """Protocol for detecting entrypoints in source code.

    Entrypoints are where external input enters the program:
    - HTTP routes (Flask, FastAPI, Django)
    - CLI commands (argparse, click, typer)
    - Queue handlers (Celery, RQ, SQS)
    - Scheduled jobs (cron, APScheduler)
    - Test functions (pytest, unittest)

    Built-in detectors handle Flask, FastAPI, and CLI scripts.
    Implement this protocol for custom patterns.
    """

    def detect(self, source: str, file_path: str) -> list[Entrypoint]:
        """Detect entrypoints in a Python source file.

        Args:
            source: The Python source code as a string.
            file_path: The path to the file being analyzed.

        Returns:
            A list of detected Entrypoint objects.

        Example implementation:
            def detect(self, source: str, file_path: str) -> list[Entrypoint]:
                module = cst.parse_module(source)
                # Walk the AST looking for your pattern
                # Return Entrypoint objects for each match
        """
        ...


class GlobalHandlerDetector(Protocol):
    """Protocol for detecting global exception handlers.

    Global handlers catch exceptions at the application level:
    - Flask @app.errorhandler(ExceptionClass)
    - FastAPI app.add_exception_handler(ExceptionClass, handler)
    - Django middleware exception handling
    - Custom error handling middleware

    Built-in detectors handle Flask and FastAPI.
    Implement this protocol for custom patterns.
    """

    def detect(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Detect global exception handlers in a Python source file.

        Args:
            source: The Python source code as a string.
            file_path: The path to the file being analyzed.

        Returns:
            A list of detected GlobalHandler objects.
        """
        ...


class DependencyDetector(Protocol):
    """Protocol for detecting implicit dependencies.

    Dependencies are functions that run before another function:
    - FastAPI Depends(some_function)
    - Decorators that call other functions
    - Context managers in function signatures

    These create implicit call edges that affect exception propagation.
    """

    def detect(self, source: str, file_path: str) -> list[tuple[str, str, str]]:
        """Detect implicit dependencies in a Python source file.

        Args:
            source: The Python source code as a string.
            file_path: The path to the file being analyzed.

        Returns:
            A list of tuples: (dependent_function, dependency_function, kind)
            where kind describes the dependency type (e.g., "fastapi_depends").
        """
        ...
