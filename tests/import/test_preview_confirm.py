from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError
from django.urls import reverse

from workouts import pending
from workouts.services import import_workouts_csv
from workouts.views import PENDING_IMPORT_KEY

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
MINIMAL = HEADER + "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,80,5,0,0,8\n"


@pytest.fixture(autouse=True)
def pending_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STRONG_PENDING_DIR", str(tmp_path / "pending"))


def stage_preview(client, text=MINIMAL):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    response = client.post(
        reverse("upload"),
        {"csv_file": SimpleUploadedFile("export.csv", text.encode(), content_type="text/csv")},
    )
    assert response.status_code == 302
    return client.session[PENDING_IMPORT_KEY]


def confirm_post(stored):
    return {
        "import_id": stored["id"],
        "fingerprint": stored["fingerprint"],
        "action": "confirm",
    }


@pytest.mark.django_db
def test_confirm_reports_a_locked_database_instead_of_a_500(client):
    stored = stage_preview(client)

    with mock.patch(
        "workouts.views.import_workouts_csv",
        side_effect=OperationalError("database is locked"),
    ):
        response = client.post(reverse("preview"), confirm_post(stored), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("preview"), 302)]
    assert "The database was busy, please try again" in response.content.decode()
    assert pending.load_summary(stored["id"]) is not None


@pytest.mark.django_db
def test_confirm_reraises_other_operational_errors(client):
    stored = stage_preview(client)

    with (
        mock.patch(
            "workouts.views.import_workouts_csv",
            side_effect=OperationalError("disk I/O error"),
        ),
        pytest.raises(OperationalError, match="disk I/O error"),
    ):
        client.post(reverse("preview"), confirm_post(stored))


@pytest.mark.django_db
def test_confirm_reports_a_concurrent_import_instead_of_a_500(client):
    stored = stage_preview(client)

    with mock.patch(
        "workouts.views.import_workouts_csv",
        side_effect=IntegrityError("UNIQUE constraint failed"),
    ):
        response = client.post(reverse("preview"), confirm_post(stored), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("preview"), 302)]
    assert (
        "Another import landed at the same time. Confirm again to merge."
        in response.content.decode()
    )
    assert pending.load_summary(stored["id"]) is not None


@pytest.mark.django_db
def test_confirm_recomputes_the_merge_against_the_database(client):
    stored = stage_preview(client)
    user = get_user_model().objects.get(username="alice")
    import_workouts_csv(user, MINIMAL)

    response = client.post(reverse("preview"), confirm_post(stored), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain == [(reverse("sessions"), 302)]
    assert (
        "Imported 0 sessions and 0 sets. (1 skipped as already stored)" in response.content.decode()
    )
