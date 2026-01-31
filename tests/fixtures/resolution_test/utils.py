"""Utility functions for resolution testing."""


def helper_func():
    """A helper function that raises an exception."""
    raise ValueError("from helper")


def ambiguous_name():
    """Function with same name as one in other.py and main.py."""
    raise TypeError("from utils")
