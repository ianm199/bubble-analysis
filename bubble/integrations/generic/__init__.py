"""Generic framework detection based on configuration."""

from bubble.integrations.generic.config import FrameworkConfig
from bubble.integrations.generic.detector import (
    detect_entrypoints,
    detect_global_handlers,
)

__all__ = [
    "FrameworkConfig",
    "detect_entrypoints",
    "detect_global_handlers",
]
