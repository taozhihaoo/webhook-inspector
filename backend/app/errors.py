"""Structured application errors.

Every error is translated by the exception handlers in ``app.main`` into a
uniform JSON envelope:

    {"error": {"code": "...", "message": "..."}}

Python tracebacks are never returned to clients.
"""


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Internal server error."

    def __init__(self, message: str | None = None, *, code: str | None = None):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        super().__init__(self.message)


class EndpointNotFound(AppError):
    status_code = 404
    code = "endpoint_not_found"
    message = "Webhook endpoint not found."


class RequestNotFound(AppError):
    status_code = 404
    code = "request_not_found"
    message = "Webhook request not found."


class EndpointExpired(AppError):
    status_code = 410
    code = "endpoint_expired"
    message = "This webhook endpoint has expired."


class EndpointDisabled(AppError):
    status_code = 409
    code = "endpoint_disabled"
    message = "This webhook endpoint is disabled."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "Request body exceeds the maximum allowed size."


class RateLimitExceeded(AppError):
    status_code = 429
    code = "rate_limit_exceeded"
    message = "Too many requests."

    def __init__(self, retry_after: int = 60, message: str | None = None):
        self.retry_after = max(1, int(retry_after))
        super().__init__(message or self.message)


class InvalidInput(AppError):
    status_code = 422
    code = "invalid_input"
    message = "Invalid input."


class ReplayBlocked(AppError):
    status_code = 400
    code = "replay_blocked"
    message = "Replay target blocked by SSRF protection."


class ReplayTimeout(AppError):
    status_code = 504
    code = "replay_timeout"
    message = "Replay target did not respond in time."


class StorageError(AppError):
    status_code = 500
    code = "storage_error"
    message = "Failed to persist data."


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Missing or invalid admin API token."
