"""Tests for statistics gathering."""


def test_stats_function_count(flask_model):
    """Counts functions correctly."""
    assert len(flask_model.functions) == 4


def test_stats_class_count(flask_model):
    """Counts classes correctly."""
    assert len(flask_model.classes) == 3


def test_stats_entrypoint_count(flask_model):
    """Counts entrypoints correctly."""
    assert len(flask_model.entrypoints) == 2


def test_stats_raise_sites(flask_model):
    """Counts raise sites correctly."""
    assert len(flask_model.raise_sites) == 2


def test_stats_exception_hierarchy_fixture(hierarchy_model):
    """Stats for exception_hierarchy fixture."""
    assert len(hierarchy_model.classes) == 6
    assert len(hierarchy_model.functions) == 0
    assert len(hierarchy_model.entrypoints) == 0
