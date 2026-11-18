import hashlib
import hmac
from functools import wraps

from django.utils import timezone
from ninja.security.base import AuthBase

from workouts.models import ApiToken

from .contract import ApiError, auth_error_response


def resolve_bearer(request):
    header = request.headers.get("Authorization", "")
    scheme, separator, secret = header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not secret:
        raise ApiError(401, "invalid_credentials", "A valid bearer token is required")

    supplied_hash = hashlib.sha256(secret.encode()).hexdigest()
    candidates = ApiToken.objects.filter(prefix=secret[:8]).select_related("owner")
    for token in candidates:
        if not hmac.compare_digest(token.key_hash, supplied_hash):
            continue
        if token.revoked_at is not None:
            break
        if token.expires_at is not None and token.expires_at <= timezone.now():
            break
        owner = token.owner
        if owner.is_active:
            request.auth = owner
            return owner
        break
    raise ApiError(401, "invalid_credentials", "A valid bearer token is required")


class BearerAuth(AuthBase):
    openapi_type = "http"
    openapi_scheme = "bearer"

    def __call__(self, request):
        return resolve_bearer(request)


def docs_auth(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            resolve_bearer(request)
        except Exception as exc:
            response = auth_error_response(exc)
            response["Cache-Control"] = "no-store"
            return response
        return view(request, *args, **kwargs)

    return wrapper
