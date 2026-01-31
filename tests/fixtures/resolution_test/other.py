"""Other module with ambiguous function name."""


def ambiguous_name():
    """Function with same name as one in utils.py and main.py."""
    raise KeyError("from other")
