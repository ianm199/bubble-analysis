"""Tests for factory-raised exception type resolution."""

from bubble.models import ProgramModel


def _raise_sites_by_function(model: ProgramModel) -> dict[str, str]:
    """Map function name -> exception_type for convenience."""
    return {rs.function: rs.exception_type for rs in model.raise_sites}


class TestFactoryRaiseResolution:
    def test_direct_constructor_unchanged(self, factory_raise_model: ProgramModel) -> None:
        """raise HTTPException(...) should stay as HTTPException."""
        sites = _raise_sites_by_function(factory_raise_model)
        assert sites["direct_raise"] == "HTTPException"

    def test_factory_resolves_to_return_type(self, factory_raise_model: ProgramModel) -> None:
        """raise http_exception(...) should resolve to HTTPException via return type."""
        sites = _raise_sites_by_function(factory_raise_model)
        assert sites["factory_raise"] == "HTTPException"

    def test_builtin_factory_resolves(self, factory_raise_model: ProgramModel) -> None:
        """raise build_value_error(...) should resolve to ValueError."""
        sites = _raise_sites_by_function(factory_raise_model)
        assert sites["builtin_factory_raise"] == "ValueError"

    def test_custom_exception_factory_resolves(self, factory_raise_model: ProgramModel) -> None:
        """raise app_error(...) should resolve to AppError."""
        sites = _raise_sites_by_function(factory_raise_model)
        assert sites["custom_factory_raise"] == "AppError"

    def test_self_method_factory_resolves(self, factory_raise_model: ProgramModel) -> None:
        """raise self.build_error(...) should resolve to ServiceError."""
        sites = _raise_sites_by_function(factory_raise_model)
        assert sites["MyService.process"] == "ServiceError"

    def test_code_preserves_original_source(self, factory_raise_model: ProgramModel) -> None:
        """The code field should still contain the original source text."""
        for rs in factory_raise_model.raise_sites:
            if rs.function == "factory_raise":
                assert "http_exception" in rs.code
                break
        else:
            raise AssertionError("factory_raise raise site not found")
