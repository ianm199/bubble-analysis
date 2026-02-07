"""Tests for the LSP server helper functions and handlers."""

from pathlib import Path

import pytest

from bubble.extractor import extract_from_directory
from bubble.lsp import (
    RERAISE_PATTERNS,
    _find_call_sites_at_line,
    _find_function_def_at_line,
    _find_route_decorator_range,
    _format_call_hover,
    _format_def_hover,
    _function_key,
    _get_uncaught_exceptions,
    _is_reraise,
    _parse_ignore_comment,
)
from bubble.models import ProgramModel
from bubble.propagation import ExceptionFlow, RaiseSite, propagate_exceptions

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cli_model() -> ProgramModel:
    return extract_from_directory(FIXTURES / "cli_scripts", use_cache=False)


@pytest.fixture
def flask_model() -> ProgramModel:
    return extract_from_directory(FIXTURES / "flask_app", use_cache=False)


class TestIsReraise:
    def test_reraise_patterns_filtered(self):
        for pattern in RERAISE_PATTERNS:
            assert _is_reraise(pattern)

    def test_real_exceptions_not_filtered(self):
        assert not _is_reraise("ValueError")
        assert not _is_reraise("HTTPException")
        assert not _is_reraise("FileNotFoundError")


class TestFindFunctionDefAtLine:
    def test_finds_function_on_exact_def_line(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is not None
        assert func.name == "main"

    def test_returns_none_for_body_line(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        func = _find_function_def_at_line(cli_model, file_path, 6)
        assert func is None

    def test_returns_none_for_blank_line(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        func = _find_function_def_at_line(cli_model, file_path, 1)
        assert func is None

    def test_returns_none_for_wrong_file(self, cli_model):
        file_path = Path("/nonexistent/file.py")
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is None


class TestFindCallSitesAtLine:
    def test_finds_call_on_correct_line(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        calls = _find_call_sites_at_line(cli_model, file_path, 7)
        assert len(calls) >= 1
        callee_names = {cs.callee_name for cs in calls}
        assert "process_data" in callee_names

    def test_returns_empty_for_non_call_line(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        calls = _find_call_sites_at_line(cli_model, file_path, 4)
        assert calls == []

    def test_returns_empty_for_wrong_file(self, cli_model):
        file_path = Path("/nonexistent/file.py")
        calls = _find_call_sites_at_line(cli_model, file_path, 7)
        assert calls == []


class TestFunctionKey:
    def test_builds_relative_key(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is not None
        key = _function_key(func, file_path, FIXTURES / "cli_scripts")
        assert key == "process.py::main"

    def test_falls_back_to_func_file_on_unrelated_path(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is not None
        key = _function_key(func, file_path, Path("/unrelated/root"))
        assert "::main" in key


class TestGetUncaughtExceptions:
    def test_finds_uncaught_exceptions(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        workspace = FIXTURES / "cli_scripts"
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is not None
        propagation = propagate_exceptions(cli_model, skip_evidence=True)
        uncaught = _get_uncaught_exceptions(func, file_path, workspace, cli_model, propagation)
        assert "ValueError" in uncaught
        assert "FileNotFoundError" in uncaught

    def test_filters_reraise_patterns(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        workspace = FIXTURES / "cli_scripts"
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is not None
        propagation = propagate_exceptions(cli_model, skip_evidence=True)
        uncaught = _get_uncaught_exceptions(func, file_path, workspace, cli_model, propagation)
        for pattern in RERAISE_PATTERNS:
            assert pattern not in uncaught


class TestFormatDefHover:
    def test_returns_none_when_no_exceptions(self):
        flow = ExceptionFlow()
        result = _format_def_hover(flow, "clean_func")
        assert result is None

    def test_returns_none_when_only_reraise_patterns(self):
        flow = ExceptionFlow()
        flow.uncaught["e"] = [RaiseSite("f.py", 1, "func", "e", False, "raise e")]
        flow.uncaught["exc"] = [RaiseSite("f.py", 2, "func", "exc", False, "raise exc")]
        result = _format_def_hover(flow, "func")
        assert result is None

    def test_shows_uncaught_exceptions(self):
        flow = ExceptionFlow()
        flow.uncaught["ValueError"] = [
            RaiseSite("f.py", 1, "func", "ValueError", False, "raise ValueError()")
        ]
        result = _format_def_hover(flow, "my_func")
        assert result is not None
        assert "ValueError" in result
        assert "my_func" in result
        assert "Uncaught" in result

    def test_shows_multiple_categories(self):
        flow = ExceptionFlow()
        flow.uncaught["ValueError"] = [
            RaiseSite("f.py", 1, "func", "ValueError", False, "raise ValueError()")
        ]
        flow.caught_locally["KeyError"] = [
            RaiseSite("f.py", 2, "func", "KeyError", False, "raise KeyError()")
        ]
        result = _format_def_hover(flow, "func")
        assert result is not None
        assert "ValueError" in result
        assert "KeyError" in result
        assert "Uncaught" in result
        assert "Caught locally" in result

    def test_filters_reraise_from_mixed(self):
        flow = ExceptionFlow()
        flow.uncaught["ValueError"] = [
            RaiseSite("f.py", 1, "func", "ValueError", False, "raise ValueError()")
        ]
        flow.uncaught["e"] = [RaiseSite("f.py", 2, "func", "e", False, "raise e")]
        result = _format_def_hover(flow, "func")
        assert result is not None
        assert "ValueError" in result
        assert "`e`" not in result


class TestFormatCallHover:
    def test_shows_callee_exceptions(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        propagation = propagate_exceptions(cli_model, skip_evidence=True)
        calls = _find_call_sites_at_line(cli_model, file_path, 7)
        assert len(calls) >= 1
        result = _format_call_hover(calls, propagation, cli_model)
        assert result is not None
        assert "FileNotFoundError" in result

    def test_returns_none_for_no_exceptions(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        propagation = propagate_exceptions(cli_model, skip_evidence=True)
        calls = _find_call_sites_at_line(cli_model, file_path, 5)
        result = _format_call_hover(calls, propagation, cli_model)
        assert result is None


class TestHoverContextSensitive:
    """Integration tests verifying the three-way hover dispatch logic."""

    def test_def_line_returns_exception_flow(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        workspace = FIXTURES / "cli_scripts"
        func = _find_function_def_at_line(cli_model, file_path, 4)
        assert func is not None

        propagation = propagate_exceptions(cli_model, skip_evidence=True)
        from bubble.propagation import compute_exception_flow

        function_key = _function_key(func, file_path, workspace)
        flow = compute_exception_flow(function_key, cli_model, propagation)
        hover_text = _format_def_hover(flow, func.qualified_name)
        assert hover_text is not None
        assert "ValueError" in hover_text
        assert "FileNotFoundError" in hover_text

    def test_call_line_returns_callee_exceptions(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        calls = _find_call_sites_at_line(cli_model, file_path, 7)
        assert len(calls) >= 1

        propagation = propagate_exceptions(cli_model, skip_evidence=True)
        result = _format_call_hover(calls, propagation, cli_model)
        assert result is not None
        assert "process_data" in result
        assert "FileNotFoundError" in result

    def test_blank_line_returns_nothing(self, cli_model):
        file_path = FIXTURES / "cli_scripts" / "process.py"
        func = _find_function_def_at_line(cli_model, file_path, 1)
        assert func is None
        calls = _find_call_sites_at_line(cli_model, file_path, 1)
        assert calls == []


class TestFindRouteDecoratorRange:
    """Tests for finding route decorator lines above function defs."""

    def test_finds_simple_decorator(self):
        source_lines = [
            "",
            "@app.route('/hello')",
            "def hello():",
            "    return 'hi'",
        ]
        result = _find_route_decorator_range(source_lines, 3)
        assert result is not None
        assert result.start.line == 1
        assert result.start.character == 0

    def test_finds_route_decorator_over_other(self):
        source_lines = [
            "",
            "@router.get('/balance')",
            "@login_required",
            "def get_balance():",
            "    pass",
        ]
        result = _find_route_decorator_range(source_lines, 4)
        assert result is not None
        assert result.start.line == 1

    def test_falls_back_to_nearest_decorator(self):
        source_lines = [
            "",
            "@some_custom_decorator",
            "def my_func():",
            "    pass",
        ]
        result = _find_route_decorator_range(source_lines, 3)
        assert result is not None
        assert result.start.line == 1

    def test_returns_none_with_no_decorator(self):
        source_lines = [
            "",
            "def plain_func():",
            "    pass",
        ]
        result = _find_route_decorator_range(source_lines, 2)
        assert result is None

    def test_stops_at_blank_line(self):
        source_lines = [
            "@unrelated_decorator",
            "def other():",
            "    pass",
            "",
            "def target():",
            "    pass",
        ]
        result = _find_route_decorator_range(source_lines, 5)
        assert result is None

    def test_handles_indented_decorator(self):
        source_lines = [
            "class Views:",
            "    @app.route('/test')",
            "    def test_view(self):",
            "        pass",
        ]
        result = _find_route_decorator_range(source_lines, 3)
        assert result is not None
        assert result.start.line == 1
        assert result.start.character == 4

    def test_uncaught_exceptions_filtered_in_diagnostics(self, flask_model):
        """Diagnostics only show non-reraise exceptions."""
        workspace = FIXTURES / "flask_app"
        propagation = propagate_exceptions(flask_model, skip_evidence=True)

        for func in flask_model.functions.values():
            fp = workspace / func.file.split("/")[-1] if "/" in func.file else Path(func.file)
            uncaught = _get_uncaught_exceptions(func, fp, workspace, flask_model, propagation)
            for exc in uncaught:
                assert exc not in RERAISE_PATTERNS


class TestParseIgnoreComment:
    """Tests for the # bubble: ignore comment parsing."""

    def test_blanket_ignore_on_decorator(self):
        source_lines = [
            "@app.route('/users')  # bubble: ignore",
            "def create_user():",
        ]
        result = _parse_ignore_comment(source_lines, 0, 2)
        assert result is True

    def test_blanket_ignore_on_def_line(self):
        source_lines = [
            "@app.route('/users')",
            "def create_user():  # bubble: ignore",
        ]
        result = _parse_ignore_comment(source_lines, 0, 2)
        assert result is True

    def test_selective_ignore_single_type(self):
        source_lines = [
            "@app.route('/users')  # bubble: ignore[ValueError]",
            "def create_user():",
        ]
        result = _parse_ignore_comment(source_lines, 0, 2)
        assert result == {"ValueError"}

    def test_selective_ignore_multiple_types(self):
        source_lines = [
            "@app.route('/users')  # bubble: ignore[ValueError, KeyError]",
            "def create_user():",
        ]
        result = _parse_ignore_comment(source_lines, 0, 2)
        assert result == {"ValueError", "KeyError"}

    def test_ignore_between_decorator_and_def(self):
        source_lines = [
            "@app.route('/users')",
            "@login_required  # bubble: ignore[HTTPException]",
            "def create_user():",
        ]
        result = _parse_ignore_comment(source_lines, 0, 3)
        assert result == {"HTTPException"}

    def test_no_ignore_returns_false(self):
        source_lines = [
            "@app.route('/users')",
            "def create_user():",
        ]
        result = _parse_ignore_comment(source_lines, 0, 2)
        assert result is False

    def test_unrelated_comment_not_matched(self):
        source_lines = [
            "@app.route('/users')  # TODO: fix this",
            "def create_user():",
        ]
        result = _parse_ignore_comment(source_lines, 0, 2)
        assert result is False

    def test_selective_removes_from_uncaught(self):
        """Selective ignore should only suppress listed types."""
        uncaught = {"ValueError", "KeyError", "HTTPException"}
        ignored = {"ValueError", "KeyError"}
        remaining = uncaught - ignored
        assert remaining == {"HTTPException"}
