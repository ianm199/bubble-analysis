"""Main module for resolution testing."""

import requests
from services import ServiceA
from utils import helper_func


def caller():
    """Caller function that exercises different resolution paths."""
    requests.get("http://example.com")
    helper_func()
    svc = ServiceA()
    svc.process()
    ambiguous_name()


def ambiguous_name():
    """Locally defined function with same name as one in other.py."""
    raise TypeError("from main")
