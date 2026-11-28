from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="sessions", permanent=False)),
    path("upload/", views.upload, name="upload"),
    path("preview/", views.preview, name="preview"),
    path("sessions/", views.sessions, name="sessions"),
    path("sessions/delete/", views.delete_sessions, name="delete_sessions"),
    path("sessions/<int:pk>/delete/", views.delete_session, name="delete_session"),
    path("sessions/undo/", views.undo_delete, name="undo_delete"),
    path("reports/", views.reports, name="reports"),
    path("reports/exercise/<path:name>/", views.report_exercise, name="report_exercise"),
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
    path("tokens/<int:pk>/delete/", views.delete_token, name="delete_token"),
]
