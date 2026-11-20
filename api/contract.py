import json
import logging
from datetime import UTC, datetime

from django.db import OperationalError
from django.http import HttpResponse

logger = logging.getLogger("django")

CONTRACT_VERSION = "1.0"
MAX_RANGE_DAYS = 1830
MAX_LIMIT = 1000
MAX_BODY_BYTES = 10 * 1024 * 1024
API_PREFIX = "/api/v1/"

STATUS_CODES = {
    400: ("bad_request", "Bad request"),
    401: ("invalid_credentials", "A valid bearer token is required"),
    403: ("permission_denied", "Permission denied"),
    404: ("not_found", "Resource not found"),
    405: ("method_not_allowed", "Method not allowed"),
    409: ("conflict", "Conflict"),
    413: ("payload_too_large", "Request body too large"),
    415: ("unsupported_media_type", "Unsupported media type"),
    422: ("validation_error", "Validation failed"),
    500: ("internal_error", "Internal server error"),
    503: ("service_unavailable", "Service temporarily unavailable"),
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class ServiceUnavailableError(ApiError):
    def __init__(self, message: str = "Service temporarily unavailable") -> None:
        super().__init__(503, "service_unavailable", message)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def envelope() -> dict:
    return {"contract_version": CONTRACT_VERSION, "generated_at": utc_now_iso()}


def error_payload(code: str, message: str, details=None) -> dict:
    return {
        **envelope(),
        "error": {"code": code, "message": message, "details": details},
    }


def error_response(status: int, code: str, message: str, details=None) -> HttpResponse:
    response = HttpResponse(
        json.dumps(error_payload(code, message, details)),
        status=status,
        content_type="application/json",
    )
    if status == 401:
        response["WWW-Authenticate"] = "Bearer"
    return response


_TRANSIENT_SQLITE_ERRORS = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})
_TRANSIENT_DB_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
)


def is_transient_db_error(exc):
    if getattr(exc.__cause__, "sqlite_errorname", None) in _TRANSIENT_SQLITE_ERRORS:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_DB_MESSAGES)


def auth_error_response(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details)
    if isinstance(exc, OperationalError) and is_transient_db_error(exc):
        logger.warning("Transient database failure during authentication: %s", exc)
        return error_response(503, "service_unavailable", "Service temporarily unavailable")
    logger.exception("Unexpected authentication failure", exc_info=exc)
    return error_response(500, "internal_error", "Internal server error")
