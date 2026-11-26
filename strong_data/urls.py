from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from django.views.defaults import bad_request as django_bad_request

from api.contract import error_response
from api.urls import api
from strong_data.views import LoginView, release_status


def bad_request(request, exception=None):
    if request.path.startswith("/api/"):
        response = error_response(400, "bad_request", "Bad request")
        response["Cache-Control"] = "no-store"
        return response
    return django_bad_request(request, exception=exception)


handler400 = bad_request
handler404 = "strong_data.views.not_found"
handler500 = "strong_data.views.server_error"

_api_patterns, _api_app_name, _api_namespace = api.urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", LoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("release-status/", release_status, name="release_status"),
    path("api/v1/", include((_api_patterns, _api_app_name), namespace=_api_namespace)),
    path("", include("workouts.urls")),
]
