"""Factory functions that return exception instances."""


class AppError(Exception):
    pass


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail


def http_exception(status_code: int, detail: str = "") -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def build_value_error(msg: str) -> ValueError:
    return ValueError(msg)


def app_error(msg: str) -> AppError:
    return AppError(msg)
