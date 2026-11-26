from .auth import resolve_bearer
from .contract import API_PREFIX, MAX_BODY_BYTES, STATUS_CODES, auth_error_response, error_response

API_ROOT = "/api/"
CONVERTED_STATUSES = (400, 404, 405)
HEALTHZ_PATH = f"{API_PREFIX}healthz"
DOCS_PATH = f"{API_PREFIX}docs"
OPENAPI_PATH = f"{API_PREFIX}openapi.json"


def _django_error_response(response):
    if response.get("Content-Type", "").startswith("application/json"):
        return None
    if response.status_code not in CONVERTED_STATUSES:
        return None
    code, message = STATUS_CODES[response.status_code]
    return error_response(response.status_code, code, message)


def _session_may_view_docs(request, path):
    if path != DOCS_PATH and not path.startswith(DOCS_PATH + "/") and path != OPENAPI_PATH:
        return False
    user = getattr(request, "user", None)
    return user is not None and user.is_authenticated


class ApiResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not path.startswith(API_ROOT):
            return self.get_response(request)
        if not path.startswith(API_PREFIX):
            response = error_response(404, "not_found", "Resource not found")
        else:
            response = self._api_v1_response(request, path)
        response["Cache-Control"] = "no-store"
        return response

    def _api_v1_response(self, request, path):
        if path != HEALTHZ_PATH:
            try:
                resolve_bearer(request)
            except Exception as exc:
                if not _session_may_view_docs(request, path):
                    return auth_error_response(exc)

        length = request.META.get("CONTENT_LENGTH", "")
        size = int(length) if length.isdigit() else 0
        if size > MAX_BODY_BYTES:
            return error_response(413, "payload_too_large", "Request body exceeds 10 MB")
        if request.method not in {"GET", "HEAD"}:
            return error_response(405, "method_not_allowed", "This API is read-only")
        if size > 0 and not (request.content_type or "").startswith("application/json"):
            return error_response(
                415, "unsupported_media_type", "Request bodies must be application/json"
            )
        response = self.get_response(request)
        converted = _django_error_response(response)
        if converted is not None:
            response = converted
        return response
