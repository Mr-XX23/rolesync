"""Domain errors. The API layer maps ``status_code``/``code`` to HTTP responses."""

from __future__ import annotations


class EngineError(Exception):
    status_code = 500
    code = "ENGINE_ERROR"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__


class AuthenticationFailed(EngineError):
    status_code = 401
    code = "UNAUTHENTICATED"


class TenantAccessDenied(EngineError):
    status_code = 403
    code = "TENANT_ACCESS_DENIED"


class BadRequest(EngineError):
    status_code = 400
    code = "BAD_REQUEST"


class NotFound(EngineError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(EngineError):
    status_code = 409
    code = "CONFLICT"


class ValidationFailed(EngineError):
    status_code = 422
    code = "VALIDATION_FAILED"


class UpstreamUnavailable(EngineError):
    status_code = 503
    code = "UPSTREAM_UNAVAILABLE"
