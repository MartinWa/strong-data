from .version import app_version

API_BASE = "/api/v1"


def app_info(request):
    return {
        "app_version": app_version(),
        "api_schema_url": f"{API_BASE}/openapi.json",
        "api_health_url": f"{API_BASE}/healthz",
    }
