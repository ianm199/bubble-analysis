"""Loader for custom detectors from .flow/detectors/."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

from bubble.models import Entrypoint, GlobalHandler
from bubble.protocols import EntrypointDetector, GlobalHandlerDetector


class DetectorRegistry:
    """Registry of custom detectors loaded from .flow/detectors/."""

    def __init__(self) -> None:
        self.entrypoint_detectors: list[EntrypointDetector] = []
        self.global_handler_detectors: list[GlobalHandlerDetector] = []
        self._loaded_modules: dict[str, Any] = {}

    def load_from_directory(self, flow_dir: Path) -> None:
        """Load all detectors from a .flow/detectors/ directory."""
        detectors_dir = flow_dir / "detectors"
        if not detectors_dir.exists():
            return

        for py_file in detectors_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            self._load_detector_file(py_file)

    def _load_detector_file(self, file_path: Path) -> None:
        """Load detectors from a single Python file."""
        module_name = f"flow_custom_detectors.{file_path.stem}"

        if module_name in self._loaded_modules:
            return

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Warning: Failed to load detector {file_path}: {e}")
            return

        self._loaded_modules[module_name] = module

        for name in dir(module):
            if name.startswith("_"):
                continue

            obj = getattr(module, name)
            if not isinstance(obj, type):
                continue

            if self._is_entrypoint_detector(obj):
                try:
                    instance = obj()
                    self.entrypoint_detectors.append(instance)
                except Exception:
                    pass

            if self._is_global_handler_detector(obj):
                try:
                    instance = obj()
                    self.global_handler_detectors.append(instance)
                except Exception:
                    pass

    def _is_entrypoint_detector(self, cls: type) -> bool:
        """Check if a class implements EntrypointDetector protocol."""
        if cls.__name__ in ("EntrypointDetector", "GlobalHandlerDetector"):
            return False
        return hasattr(cls, "detect") and callable(cls.detect)

    def _is_global_handler_detector(self, cls: type) -> bool:
        """Check if a class implements GlobalHandlerDetector protocol."""
        if cls.__name__ in ("EntrypointDetector", "GlobalHandlerDetector"):
            return False
        return hasattr(cls, "detect") and callable(cls.detect)

    def detect_entrypoints(self, source: str, file_path: str) -> list[Entrypoint]:
        """Run all custom entrypoint detectors on a source file."""
        results: list[Entrypoint] = []
        for detector in self.entrypoint_detectors:
            try:
                detected = detector.detect(source, file_path)
                if detected:
                    results.extend(detected)
            except Exception:
                pass
        return results

    def detect_global_handlers(self, source: str, file_path: str) -> list[GlobalHandler]:
        """Run all custom global handler detectors on a source file."""
        results: list[GlobalHandler] = []
        for detector in self.global_handler_detectors:
            try:
                detected = detector.detect(source, file_path)
                if detected:
                    results.extend(detected)
            except Exception:
                pass
        return results


def load_detectors(directory: Path) -> DetectorRegistry:
    """Load custom detectors from a project's .flow/ directory."""
    registry = DetectorRegistry()
    flow_dir = directory / ".flow"
    if flow_dir.exists():
        registry.load_from_directory(flow_dir)
    return registry
