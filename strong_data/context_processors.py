from django.conf import settings

from .releases import RELEASES_URL, REPOSITORY_URL, version_number
from .version import app_version

API_BASE = "/api/v1"


def app_info(request):
    info = {
        "csp_nonce": getattr(request, "csp_nonce", ""),
        "app_repository_url": REPOSITORY_URL,
        "app_releases_url": RELEASES_URL,
        "app_check_updates": settings.UPDATE_CHECK_ENABLED,
        "api_docs_url": f"{API_BASE}/docs",
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        version = app_version()
        info["app_version"] = version
        info["app_is_release"] = version_number(version) is not None
    return info
