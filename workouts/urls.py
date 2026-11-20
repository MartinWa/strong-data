from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="sessions", permanent=False)),
    path("upload/", views.upload, name="upload"),
    path("preview/", views.preview, name="preview"),
    path("sessions/", views.sessions, name="sessions"),
    path("sessions/delete/", views.delete_sessions, name="delete_sessions"),
    path(
        "history/",
        RedirectView.as_view(pattern_name="sessions", permanent=True, query_string=True),
        name="legacy_history",
    ),
    path("muscles/", views.muscles, name="muscles"),
    path("muscles/groups/delete/", views.delete_group, name="delete_group"),
    path(
        "corrections/",
        RedirectView.as_view(pattern_name="muscles", permanent=True),
        name="legacy_corrections",
    ),
    path("tokens/", views.tokens, name="tokens"),
    path("tokens/<int:pk>/revoke/", views.revoke_token, name="revoke_token"),
]
