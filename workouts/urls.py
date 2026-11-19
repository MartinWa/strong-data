from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="sessions", permanent=False)),
    path("upload/", views.upload, name="upload"),
    path("preview/", views.preview, name="preview"),
    path("sessions/", views.sessions, name="sessions"),
    path(
        "history/",
        RedirectView.as_view(pattern_name="sessions", permanent=True),
        name="legacy_history",
    ),
    path("corrections/", views.corrections, name="corrections"),
    path("tokens/", views.tokens, name="tokens"),
    path("tokens/<int:pk>/revoke/", views.revoke_token, name="revoke_token"),
]
