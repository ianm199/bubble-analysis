"""Class with self.method() factory pattern for exception building."""


class ServiceError(Exception):
    pass


class MyService:
    def build_error(self, msg: str) -> ServiceError:
        return ServiceError(msg)

    def process(self) -> None:
        raise self.build_error("something failed")
