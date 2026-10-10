"""Application errors. Raised by services; turned into JSON responses by ``app.api.errors``."""


class AppError(Exception):
    """An expected failure with an HTTP status, a stable machine-readable code and a message."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(resource: str) -> AppError:
    # Same response whether the record is missing or owned by someone else.
    return AppError(404, "NOT_FOUND", f"{resource} not found.")
