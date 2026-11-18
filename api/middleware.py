from .auth import resolve_bearer
from .contract import API_PREFIX, MAX_BODY_BYTES, auth_error_response, error_response


def _django_error_response(response):
    if response.get("Content-Type", "").startswith("application/json"):
        return None
    if response.status_code == 404:
        return error_response(404, "not_found", "Resource not found")
    if response.status_code == 405:
        return error_response(405, "method_not_allowed", "Method not allowed")
    return None


class ApiResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(API_PREFIX):
            return self.get_response(request)

        if request.path.rstrip("/") == API_PREFIX.rstrip("/"):
            try:
                resolve_bearer(request)
            except Exception as exc:
                response = auth_error_response(exc)
                response["Cache-Control"] = "no-store"
                return response

        length = request.META.get("CONTENT_LENGTH", "")
        size = int(length) if length.isdigit() else 0
        if size > MAX_BODY_BYTES:
            response = error_response(413, "payload_too_large", "Request body exceeds 10 MB")
        elif request.method not in {"GET", "HEAD"}:
            response = error_response(405, "method_not_allowed", "This API is read-only")
        elif size > 0 and not (request.content_type or "").startswith("application/json"):
            response = error_response(
                415, "unsupported_media_type", "Request bodies must be application/json"
            )
        else:
            response = self.get_response(request)
            converted = _django_error_response(response)
            if converted is not None:
                response = converted

        response["Cache-Control"] = "no-store"
        return response
