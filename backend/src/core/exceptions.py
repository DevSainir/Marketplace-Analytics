"""Domain-agnostic application exceptions.

These exceptions carry semantic meaning independent of the transport layer. The
presentation layer (routers / a global exception handler) is responsible for
translating them into concrete HTTP responses, preserving the Clean
Architecture rule that services never manufacture ``fastapi.HTTPException``
objects for pure business failures.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all expected application-level errors."""

    #: Machine-readable error code surfaced to API clients.
    code: str = "app_error"
    #: Suggested HTTP status the presentation layer should map this error to.
    http_status: int = 500

    def __init__(self, message: str | None = None) -> None:
        """Store an optional human-readable message alongside the class code."""
        self.message = message or self.__class__.__doc__ or self.code
        super().__init__(self.message)


class NotFoundError(AppError):
    """Requested entity does not exist."""

    code = "not_found"
    http_status = 404


class ConflictError(AppError):
    """Operation conflicts with the current persisted state."""

    code = "conflict"
    http_status = 409


class ValidationError(AppError):
    """A request parameter is semantically invalid (e.g. start after end)."""

    code = "unprocessable_entity"
    http_status = 422


class AuthenticationError(AppError):
    """Credentials are missing, malformed, or invalid."""

    code = "unauthorized"
    http_status = 401


class TokenReuseError(AuthenticationError):
    """A previously consumed refresh token was replayed (breach detected)."""

    code = "token_reuse_detected"
    http_status = 401


class PermissionDeniedError(AppError):
    """Authenticated principal lacks the required permission."""

    code = "forbidden"
    http_status = 403


class RateLimitError(AppError):
    """Client exceeded the request budget for a protected surface."""

    code = "rate_limited"
    http_status = 429


class IntegrationError(AppError):
    """An upstream/external service (e.g. WildBerries) failed."""

    code = "integration_error"
    http_status = 502
