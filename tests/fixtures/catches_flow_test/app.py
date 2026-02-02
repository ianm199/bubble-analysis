"""Test fixture for flow-aware catches testing."""


class ServiceError(Exception):
    pass


class ValidationError(ServiceError):
    pass


class NetworkError(Exception):
    pass


class UnusedException(Exception):
    pass


def api_endpoint():
    """Entry point that calls service layer."""
    try:
        result = service_layer()
        return result
    except ValidationError:
        return {"error": "validation failed"}


def service_layer():
    """Service that calls validator."""
    data = get_data()
    validate(data)
    return process(data)


def validate(data):
    """Raises ValidationError."""
    if not data:
        raise ValidationError("Data is empty")


def get_data():
    return {"key": "value"}


def process(data):
    return data


def unrelated_function():
    """This function has a try/except but is NOT in the call path."""
    try:
        do_something()
    except ValidationError:
        pass
    except ServiceError:
        pass


def do_something():
    """Does not raise ValidationError."""
    pass


def another_unrelated():
    """Catches NetworkError - completely different exception."""
    try:
        make_request()
    except NetworkError:
        pass


def make_request():
    """Raises NetworkError."""
    raise NetworkError("Connection failed")
