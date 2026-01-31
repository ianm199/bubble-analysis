"""Service classes for resolution testing."""


class ServiceA:
    """A service class."""

    def process(self):
        """Process method that raises an exception."""
        raise RuntimeError("from ServiceA")


class ServiceB:
    """Another service class with same method name."""

    def process(self):
        """Process method that raises a different exception."""
        raise OSError("from ServiceB")
