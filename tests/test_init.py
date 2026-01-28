"""Tests for flow init command (requires subprocess)."""

import subprocess
import sys


def test_init_creates_flow_directory(temp_project):
    """Init creates .flow/ directory."""
    result = subprocess.run(
        [sys.executable, "-m", "flow.cli", "init", "-d", str(temp_project)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (temp_project / ".flow").is_dir()


def test_init_creates_config(temp_project):
    """Init creates config.yaml file."""
    subprocess.run(
        [sys.executable, "-m", "flow.cli", "init", "-d", str(temp_project)],
        capture_output=True,
        text=True,
    )

    config_path = temp_project / ".flow" / "config.yaml"
    assert config_path.exists()


def test_init_creates_detectors_dir(temp_project):
    """Init creates detectors/ directory."""
    subprocess.run(
        [sys.executable, "-m", "flow.cli", "init", "-d", str(temp_project)],
        capture_output=True,
        text=True,
    )

    detectors_path = temp_project / ".flow" / "detectors"
    assert detectors_path.is_dir()


def test_init_creates_example_detector(temp_project):
    """Init creates example detector file."""
    subprocess.run(
        [sys.executable, "-m", "flow.cli", "init", "-d", str(temp_project)],
        capture_output=True,
        text=True,
    )

    example_path = temp_project / ".flow" / "detectors" / "_example.py"
    assert example_path.exists()


def test_init_detects_flask(flask_fixture, temp_project):
    """Init detects Flask framework from imports."""
    app_content = (flask_fixture / "app.py").read_text()
    (temp_project / "app.py").write_text(app_content)

    errors_content = (flask_fixture / "errors.py").read_text()
    (temp_project / "errors.py").write_text(errors_content)

    result = subprocess.run(
        [sys.executable, "-m", "flow.cli", "init", "-d", str(temp_project)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    config_content = (temp_project / ".flow" / "config.yaml").read_text()
    assert "flask" in config_content.lower()


def test_init_already_exists(temp_project):
    """Init fails if .flow/ already exists."""
    (temp_project / ".flow").mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "flow.cli", "init", "-d", str(temp_project)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
