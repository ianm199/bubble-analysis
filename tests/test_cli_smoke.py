"""CLI smoke tests - verify commands run via subprocess."""

from conftest import run_cli, run_cli_json


def test_cli_stats_runs():
    """Stats command runs and returns valid output."""
    result = run_cli("stats")
    assert result.returncode == 0
    assert "Functions" in result.stdout or "functions" in result.stdout.lower()


def test_cli_stats_json():
    """Stats command returns valid JSON."""
    data = run_cli_json("stats")
    assert "results" in data
    assert "functions" in data["results"]


def test_cli_entrypoints_runs():
    """Entrypoints command runs."""
    result = run_cli("entrypoints")
    assert result.returncode == 0


def test_cli_raises_runs():
    """Raises command runs."""
    result = run_cli("raises", "ValidationError")
    assert result.returncode == 0


def test_cli_exceptions_runs():
    """Exceptions command runs."""
    result = run_cli("exceptions", fixture="exception_hierarchy")
    assert result.returncode == 0


def test_cli_callers_runs():
    """Callers command runs."""
    result = run_cli("callers", "validate_input")
    assert result.returncode == 0


def test_cli_escapes_runs():
    """Escapes command runs."""
    result = run_cli("escapes", "validate_input")
    assert result.returncode == 0


def test_cli_catches_runs():
    """Catches command runs."""
    result = run_cli("catches", "AppError")
    assert result.returncode == 0


def test_cli_trace_runs():
    """Trace command runs and shows tree output."""
    result = run_cli("trace", "create_user")
    assert result.returncode == 0
    assert "ValidationError" in result.stdout


def test_cli_trace_json():
    """Trace command returns valid JSON."""
    data = run_cli_json("trace", "create_user")
    assert "tree" in data
    assert data["tree"]["function"] == "create_user"


def test_cli_escapes_strict():
    """Escapes command with --strict flag runs."""
    result = run_cli("escapes", "validate_input", "--strict")
    assert result.returncode == 0


def test_cli_stubs_list():
    """Stubs list command runs and shows loaded stubs."""
    result = run_cli("stubs", "list", fixture=None)
    assert result.returncode == 0
    assert "requests" in result.stdout or "Loaded" in result.stdout


def test_cli_stubs_validate():
    """Stubs validate command runs and validates built-in stubs."""
    result = run_cli("stubs", "validate", fixture=None)
    assert result.returncode == 0
    assert "valid" in result.stdout.lower()
