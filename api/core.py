import logging

from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.http import Http404
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, AuthorizationError, HttpError, ValidationError

from .auth import BearerAuth, docs_auth
from .contract import ApiError, error_response

logger = logging.getLogger("django")

_STATUS_CODES = {
    400: ("bad_request", "Bad request"),
    401: ("invalid_credentials", "A valid bearer token is required"),
    403: ("permission_denied", "Permission denied"),
    404: ("not_found", "Resource not found"),
    405: ("method_not_allowed", "Method not allowed"),
    409: ("conflict", "Conflict"),
    413: ("payload_too_large", "Request body too large"),
    415: ("unsupported_media_type", "Unsupported media type"),
    422: ("validation_error", "Validation failed"),
    429: ("throttled", "Too many requests"),
    500: ("internal_error", "Internal server error"),
    503: ("service_unavailable", "Service temporarily unavailable"),
}


def _from_status(status, message=None, details=None):
    code, default_message = _STATUS_CODES.get(status, ("error", "Request failed"))
    return error_response(status, code, message or default_message, details)


api = NinjaAPI(
    title="strong-data API",
    version="1.0.0",
    description="Read-only, owner-scoped workout data API.",
    openapi_url="/openapi.json",
    docs_url=None,
    urls_namespace="api-v1",
    auth=BearerAuth(),
    docs_decorator=docs_auth,
)


def _handle_api_error(request, exc):
    return error_response(exc.status, exc.code, exc.message, exc.details)


def _handle_http_error(request, exc):
    return _from_status(exc.status_code, str(exc))


def _handle_validation(request, exc):
    return error_response(422, "validation_error", "Validation failed", exc.errors)


def _handle_404(request, exc):
    return _from_status(404)


def _handle_permission(request, exc):
    return _from_status(403)


def _handle_operational(request, exc):
    logger.warning("Transient database failure: %s", exc)
    return _from_status(503)


def _handle_unexpected(request, exc):
    logger.exception("Unhandled API error", exc_info=exc)
    return _from_status(500)


api.add_exception_handler(ApiError, _handle_api_error)
api.add_exception_handler(AuthenticationError, _handle_http_error)
api.add_exception_handler(AuthorizationError, _handle_http_error)
api.add_exception_handler(HttpError, _handle_http_error)
api.add_exception_handler(ValidationError, _handle_validation)
api.add_exception_handler(Http404, _handle_404)
api.add_exception_handler(PermissionDenied, _handle_permission)
api.add_exception_handler(OperationalError, _handle_operational)
api.add_exception_handler(Exception, _handle_unexpected)
