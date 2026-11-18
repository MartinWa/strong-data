import json
from datetime import UTC, datetime

from django.http import HttpResponse

CONTRACT_VERSION = "1.0"
MAX_RANGE_DAYS = 1830
MAX_LIMIT = 200
MAX_BODY_BYTES = 10 * 1024 * 1024
API_PREFIX = "/api/v1/"


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
