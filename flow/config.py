"""Configuration loading for flow analysis."""

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

ResolutionMode = Literal["strict", "default", "aggressive"]


@dataclass
class FlowConfig:
    """Configuration for flow analysis."""

    resolution_mode: ResolutionMode = "default"
    exclude: list[str] = field(default_factory=list)
    handled_base_classes: list[str] = field(default_factory=list)
    async_boundaries: list[str] = field(default_factory=list)

    def is_async_boundary(self, callee_name: str) -> bool:
        """Check if a callee matches an async boundary pattern."""
        for pattern in self.async_boundaries:
            if fnmatch.fnmatch(callee_name, pattern):
                return True
            if "." in callee_name:
                method_name = callee_name.split(".")[-1]
                if fnmatch.fnmatch(method_name, pattern.lstrip("*.")):
                    return True
        return False


def load_config(directory: Path) -> FlowConfig:
    """Load configuration from .flow/config.yaml if it exists."""
    config_path = directory / ".flow" / "config.yaml"
    if not config_path.exists():
        return FlowConfig()

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    mode = data.get("resolution_mode", "default")
    if mode not in ("strict", "default", "aggressive"):
        mode = "default"

    return FlowConfig(
        resolution_mode=mode,
        exclude=data.get("exclude", []),
        handled_base_classes=data.get("handled_base_classes", []),
        async_boundaries=data.get("async_boundaries", []),
    )
