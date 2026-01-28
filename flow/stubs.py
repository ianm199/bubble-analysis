"""Exception stubs for external libraries."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class StubLibrary:
    """Collection of exception stubs for external libraries."""

    stubs: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def get_raises(self, module: str, function: str) -> list[str]:
        """Get exceptions that a function can raise."""
        module_stubs = self.stubs.get(module, {})
        return module_stubs.get(function, [])

    def add_stub(self, module: str, function: str, exceptions: list[str]) -> None:
        """Add a stub for a function."""
        if module not in self.stubs:
            self.stubs[module] = {}
        self.stubs[module][function] = exceptions


def _load_stub_file(library: StubLibrary, yaml_file: Path) -> None:
    """Load stubs from a YAML file into the library."""
    with open(yaml_file) as f:
        data = yaml.safe_load(f)

    if not data:
        return

    module = data.get("module", yaml_file.stem)
    functions = data.get("functions", {})

    for func_name, exceptions in functions.items():
        if isinstance(exceptions, list):
            library.add_stub(module, func_name, exceptions)


def load_stubs(directory: Path) -> StubLibrary:
    """Load all stub files from built-in and user directories."""
    library = StubLibrary()

    builtin_dir = Path(__file__).parent / "stubs"
    user_dir = directory / ".flow" / "stubs"

    for stub_dir in [builtin_dir, user_dir]:
        if stub_dir.exists():
            for yaml_file in stub_dir.glob("*.yaml"):
                _load_stub_file(library, yaml_file)

    return library


def validate_stub_file(yaml_file: Path) -> list[str]:
    """Validate a stub file and return any errors."""
    errors: list[str] = []

    try:
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML syntax error: {e}")
        return errors

    if not isinstance(data, dict):
        errors.append("Root must be a dictionary")
        return errors

    if "module" not in data:
        errors.append("Missing 'module' key")

    if "functions" not in data:
        errors.append("Missing 'functions' key")
    elif not isinstance(data["functions"], dict):
        errors.append("'functions' must be a dictionary")
    else:
        for func_name, exceptions in data["functions"].items():
            if not isinstance(exceptions, list):
                errors.append(f"'{func_name}' must map to a list of exceptions")
            else:
                for exc in exceptions:
                    if not isinstance(exc, str):
                        errors.append(f"Exception in '{func_name}' must be a string")

    return errors
