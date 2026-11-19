from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from api.urls import api
from strong_data.views import LoginView, release_status

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
