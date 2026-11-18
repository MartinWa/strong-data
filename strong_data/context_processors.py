from django.urls import reverse

from .version import app_version

API_BASE = "/api/v1"


def app_info(request):
    return {
        "app_version": app_version(),
        "api_reference_url": reverse("api_reference"),
        "api_schema_url": f"{API_BASE}/openapi.json",
        "api_health_url": f"{API_BASE}/healthz",
    }
