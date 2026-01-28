class BaseAppError(Exception):
    pass


class ClientError(BaseAppError):
    pass


class ValidationError(ClientError):
    pass


class AuthError(ClientError):
    pass


class ServerError(BaseAppError):
    pass


class DatabaseError(ServerError):
    pass
