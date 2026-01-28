"""Configuration loading for flow analysis."""

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
    )
