class UseCaseError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(UseCaseError):
    status_code = 422


class NotFoundError(UseCaseError):
    status_code = 404


class ConflictError(UseCaseError):
    status_code = 409


class AuthError(UseCaseError):
    status_code = 401


class TooManyAttemptsError(UseCaseError):
    status_code = 429


class ExternalServiceError(UseCaseError):
    status_code = 502
