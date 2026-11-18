from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from api.urls import api

_api_patterns, _api_app_name, _api_namespace = api.urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("accounts/logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("api/v1/", include((_api_patterns, _api_app_name), namespace=_api_namespace)),
    path("", include("workouts.urls")),
]
