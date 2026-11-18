import logging

from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.http import Http404
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, AuthorizationError, HttpError, ValidationError
from ninja.schema import NinjaGenerateJsonSchema
from pydantic.json_schema import models_json_schema

from .auth import BearerAuth, docs_auth
from .contract import ApiError, error_response
from .schemas import ErrorOut

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

_DOCUMENTED_ERRORS = {
    status: message for status, (_, message) in _STATUS_CODES.items() if status != 429
}

_TRANSIENT_SQLITE_ERRORS = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})
_TRANSIENT_DB_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
)


def _is_transient_db_error(exc):
    if getattr(exc.__cause__, "sqlite_errorname", None) in _TRANSIENT_SQLITE_ERRORS:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_DB_MESSAGES)


def _document_error_responses(schema):
    refs, definitions = models_json_schema(
        [(ErrorOut, "serialization")],
        ref_template="#/components/schemas/{model}",
        schema_generator=NinjaGenerateJsonSchema,
    )
    schema["components"]["schemas"].update(definitions.get("$defs", {}))
    content = {"application/json": {"schema": refs[(ErrorOut, "serialization")]}}
    for methods in schema["paths"].values():
        for operation in methods.values():
            statuses = dict(_DOCUMENTED_ERRORS)
            if "security" not in operation:
                statuses.pop(401, None)
            responses = operation.setdefault("responses", {})
            for status, description in statuses.items():
                responses.setdefault(status, {"description": description, "content": content})


class DocumentedNinjaAPI(NinjaAPI):
    def get_openapi_schema(self, *, path_prefix=None, path_params=None):
        schema = super().get_openapi_schema(path_prefix=path_prefix, path_params=path_params)
        _document_error_responses(schema)
        return schema


def _from_status(status, message=None, details=None):
    code, default_message = _STATUS_CODES.get(status, ("error", "Request failed"))
    return error_response(status, code, message or default_message, details)


api = DocumentedNinjaAPI(
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
    if _is_transient_db_error(exc):
        logger.warning("Transient database failure: %s", exc)
        return _from_status(503)
    logger.exception("Unexpected database error", exc_info=exc)
    return _from_status(500)


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
