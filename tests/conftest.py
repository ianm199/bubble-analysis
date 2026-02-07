import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from bubble.extractor import extract_from_directory
from bubble.models import ProgramModel
from bubble.propagation import clear_propagation_cache

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear propagation caches before each test to prevent test pollution."""
    clear_propagation_cache()


@pytest.fixture
def flask_model() -> ProgramModel:
    """Pre-built model for flask_app fixture."""
    return extract_from_directory(FIXTURES / "flask_app", use_cache=False)


@pytest.fixture
def fastapi_model() -> ProgramModel:
    """Pre-built model for fastapi_app fixture."""
    return extract_from_directory(FIXTURES / "fastapi_app", use_cache=False)


@pytest.fixture
def cli_model() -> ProgramModel:
    """Pre-built model for cli_scripts fixture."""
    return extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)


@pytest.fixture
def hierarchy_model() -> ProgramModel:
    """Pre-built model for exception_hierarchy fixture."""
    return extract_from_directory(FIXTURES / "exception_hierarchy", use_cache=False)


@pytest.fixture
def mixed_model() -> ProgramModel:
    """Pre-built model for mixed_app fixture."""
    return extract_from_directory(FIXTURES / "mixed_app", use_cache=False)


@pytest.fixture
def resolution_model() -> ProgramModel:
    """Pre-built model for resolution_test fixture."""
    return extract_from_directory(FIXTURES / "resolution_test", use_cache=False)


@pytest.fixture
def flask_appbuilder_model() -> ProgramModel:
    """Pre-built model for flask_appbuilder_app fixture."""
    return extract_from_directory(FIXTURES / "flask_appbuilder_app", use_cache=False)


@pytest.fixture
def generic_handler_model() -> ProgramModel:
    """Pre-built model for generic_handler_app fixture."""
    return extract_from_directory(FIXTURES / "generic_handler_app", use_cache=False)


@pytest.fixture
def flask_restful_model() -> ProgramModel:
    """Pre-built model for flask_restful_app fixture."""
    return extract_from_directory(FIXTURES / "flask_restful_app", use_cache=False)


@pytest.fixture
def flask_restful_crossfile_model() -> ProgramModel:
    """Pre-built model for flask_restful_crossfile fixture (cross-file correlation test)."""
    return extract_from_directory(FIXTURES / "flask_restful_crossfile", use_cache=False)


@pytest.fixture
def catches_flow_model() -> ProgramModel:
    """Pre-built model for catches_flow_test fixture (flow-aware catches testing)."""
    return extract_from_directory(FIXTURES / "catches_flow_test", use_cache=False)


@pytest.fixture
def factory_raise_model() -> ProgramModel:
    """Pre-built model for factory_raise fixture."""
    return extract_from_directory(FIXTURES / "factory_raise", use_cache=False)


@pytest.fixture
def remote_handler_model() -> ProgramModel:
    """Pre-built model for remote_handler_app fixture (cross-file handler testing)."""
    return extract_from_directory(FIXTURES / "remote_handler_app", use_cache=False)


@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def flask_fixture():
    """Path to Flask fixture."""
    return FIXTURES / "flask_app"


def run_cli(*args: str, fixture: str | None = "flask_app") -> subprocess.CompletedProcess[str]:
    """Run flow CLI command via subprocess (for smoke tests only)."""
    cmd = [sys.executable, "-m", "bubble.cli", *args]
    if fixture is not None:
        cmd.extend(["--no-cache", "-d", str(FIXTURES / fixture)])
    return subprocess.run(cmd, capture_output=True, text=True)


def run_cli_json(*args: str, fixture: str | None = "flask_app") -> dict:
    """Run flow CLI and parse JSON output."""
    result = run_cli(*args, "-f", "json", fixture=fixture)
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    return json.loads(result.stdout)
