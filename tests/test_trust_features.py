"""Tests for trust features: evidence, confidence, resolution modes, stubs, framework detection."""

from pathlib import Path

from flow.config import FlowConfig, load_config
from flow.detectors import FRAMEWORK_EXCEPTION_RESPONSES
from flow.enums import ConfidenceLevel, ResolutionKind, ResolutionMode
from flow.extractor import extract_from_directory
from flow.models import ResolutionEdge, compute_confidence
from flow.propagation import propagate_exceptions
from flow.stubs import load_stubs, validate_stub_file

FIXTURES = Path(__file__).parent / "fixtures"


class TestResolutionEdgeAndConfidence:
    """Tests for ResolutionEdge and confidence computation."""

    def test_compute_confidence_high(self):
        """High confidence when all resolutions are precise."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.IMPORT,
                is_heuristic=False,
            ),
            ResolutionEdge(
                caller="b",
                callee="c",
                file="f.py",
                line=2,
                resolution_kind=ResolutionKind.SELF,
                is_heuristic=False,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.HIGH

    def test_compute_confidence_medium(self):
        """Medium confidence when return_type resolution is used."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.RETURN_TYPE,
                is_heuristic=False,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.MEDIUM

    def test_compute_confidence_medium_unambiguous_name_fallback(self):
        """Medium confidence when unambiguous name_fallback is used (match_count=1)."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.NAME_FALLBACK,
                is_heuristic=True,
                match_count=1,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.MEDIUM

    def test_compute_confidence_low_ambiguous_name_fallback(self):
        """Low confidence when ambiguous name_fallback is used (match_count>1)."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.NAME_FALLBACK,
                is_heuristic=True,
                match_count=3,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.LOW

    def test_compute_confidence_low_polymorphic(self):
        """Low confidence when polymorphic resolution is used."""
        edges = [
            ResolutionEdge(
                caller="a",
                callee="b",
                file="f.py",
                line=1,
                resolution_kind=ResolutionKind.POLYMORPHIC,
                is_heuristic=True,
            ),
        ]
        assert compute_confidence(edges) == ConfidenceLevel.LOW

    def test_compute_confidence_empty_path(self):
        """High confidence for empty path (direct raise)."""
        assert compute_confidence([]) == ConfidenceLevel.HIGH


class TestResolutionModes:
    """Tests for resolution mode filtering."""

    def test_strict_mode_filters_heuristics(self):
        """Strict mode filters out heuristic-based resolutions."""
        model = extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)

        default_result = propagate_exceptions(model, resolution_mode=ResolutionMode.DEFAULT)
        strict_result = propagate_exceptions(model, resolution_mode=ResolutionMode.STRICT)

        default_total = sum(len(excs) for excs in default_result.propagated_raises.values())
        strict_total = sum(len(excs) for excs in strict_result.propagated_raises.values())

        assert strict_total <= default_total

    def test_default_mode_includes_fallback(self):
        """Default mode includes name_fallback resolutions."""
        model = extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)
        result = propagate_exceptions(model, resolution_mode=ResolutionMode.DEFAULT)

        has_propagation = any(excs for excs in result.propagated_raises.values() if excs)
        assert has_propagation


class TestStubLibrary:
    """Tests for exception stub loading."""

    def test_load_builtin_stubs(self):
        """Built-in stubs are loaded correctly."""
        library = load_stubs(Path("."))

        assert "requests" in library.stubs
        assert "sqlalchemy" in library.stubs
        assert "boto3" in library.stubs

    def test_stub_get_raises(self):
        """Stub library returns exceptions for known functions."""
        library = load_stubs(Path("."))

        requests_get_raises = library.get_raises("requests", "get")
        assert len(requests_get_raises) > 0
        assert any("ConnectionError" in exc for exc in requests_get_raises)

    def test_stub_unknown_function(self):
        """Stub library returns empty list for unknown functions."""
        library = load_stubs(Path("."))

        raises = library.get_raises("requests", "nonexistent_function")
        assert raises == []

    def test_stub_unknown_module(self):
        """Stub library returns empty list for unknown modules."""
        library = load_stubs(Path("."))

        raises = library.get_raises("nonexistent_module", "get")
        assert raises == []

    def test_validate_stub_file(self):
        """Built-in stub files pass validation."""
        stub_dir = Path(__file__).parent.parent / "flow" / "stubs"
        for yaml_file in stub_dir.glob("*.yaml"):
            errors = validate_stub_file(yaml_file)
            assert errors == [], f"Errors in {yaml_file.name}: {errors}"


class TestFrameworkDetection:
    """Tests for framework detection."""

    def test_framework_exception_responses_defined(self):
        """Framework exception responses are defined."""
        assert "flask" in FRAMEWORK_EXCEPTION_RESPONSES
        assert "fastapi" in FRAMEWORK_EXCEPTION_RESPONSES

    def test_flask_http_exception_mapping(self):
        """Flask HTTPException maps to HTTP response."""
        flask_responses = FRAMEWORK_EXCEPTION_RESPONSES["flask"]
        assert "HTTPException" in flask_responses

    def test_fastapi_http_exception_mapping(self):
        """FastAPI HTTPException maps to HTTP response."""
        fastapi_responses = FRAMEWORK_EXCEPTION_RESPONSES["fastapi"]
        assert "HTTPException" in fastapi_responses

    def test_fastapi_validation_error_mapping(self):
        """FastAPI ValidationError maps to HTTP 422."""
        fastapi_responses = FRAMEWORK_EXCEPTION_RESPONSES["fastapi"]
        assert "ValidationError" in fastapi_responses
        assert "422" in fastapi_responses["ValidationError"]

    def test_flask_framework_detected_from_imports(self):
        """Flask framework is detected from imports."""
        model = extract_from_directory(FIXTURES / "flask_app", use_cache=False)
        assert "flask" in model.detected_frameworks

    def test_fastapi_framework_detected_from_imports(self):
        """FastAPI framework is detected from imports."""
        model = extract_from_directory(FIXTURES / "fastapi_app", use_cache=False)
        assert "fastapi" in model.detected_frameworks


class TestConfig:
    """Tests for configuration loading."""

    def test_default_config(self):
        """Default config has expected values."""
        config = FlowConfig()
        assert config.resolution_mode == "default"
        assert config.exclude == []

    def test_load_config_missing_file(self, tmp_path):
        """Missing config file returns defaults."""
        config = load_config(tmp_path)
        assert config.resolution_mode == "default"

    def test_load_config_from_file(self, tmp_path):
        """Config is loaded from file."""
        flow_dir = tmp_path / ".flow"
        flow_dir.mkdir()
        config_file = flow_dir / "config.yaml"
        config_file.write_text("resolution_mode: strict\nexclude:\n  - vendor\n")

        config = load_config(tmp_path)
        assert config.resolution_mode == "strict"
        assert "vendor" in config.exclude


class TestPropagationEvidence:
    """Tests for propagation evidence tracking."""

    def test_propagated_with_evidence_populated(self):
        """Propagation result includes evidence."""
        model = extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)
        result = propagate_exceptions(model)

        assert hasattr(result, "propagated_with_evidence")

    def test_evidence_has_raise_site(self):
        """Evidence includes raise site information."""
        model = extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)
        result = propagate_exceptions(model)

        for func_evidence in result.propagated_with_evidence.values():
            for key, prop_raise in func_evidence.items():
                assert prop_raise.raise_site is not None
                assert prop_raise.exception_type == key[0]
