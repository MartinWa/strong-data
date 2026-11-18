import csv
import hashlib

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from strong_data.version import app_version
from workouts.models import ApiToken, ExerciseMeta, WorkoutSession
from workouts.services import import_workouts_csv

CSV = (
    "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
    "2026-01-05 09:00:00,Push Day #1,54m,Bench Press (Barbell),1,80,5,0,0,8.0\n"
    "2026-01-05 09:05:00,Push Day #1,54m,Chest Fly,1,,,0,0,\n"
)


def upload(client, text=CSV):
    return client.post(
        reverse("upload"),
        {"csv_file": SimpleUploadedFile("export.csv", text.encode(), content_type="text/csv")},
    )


@pytest.fixture
def small_field_limit():
    original = csv.field_size_limit()
    csv.field_size_limit(13)
    yield
    csv.field_size_limit(original)


@pytest.mark.django_db
def test_footer_shows_version_and_api_links(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert app_version().encode() in response.content
    assert b"/api-reference/" in response.content
    assert b"/api/v1/healthz" in response.content


def test_api_reference_is_readable_without_a_token(client):
    response = client.get(reverse("api_reference"))

    assert response.status_code == 200
    assert b"/series/volume" in response.content
    assert b"/api/v1/openapi.json" in response.content
    assert b"returns 401" in response.content


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["upload", "history", "corrections", "tokens"])
def test_views_require_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302
    assert reverse("login") in response.url


@pytest.mark.django_db
def test_upload_preview_confirm_flow(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = upload(client)
    assert response.status_code == 302
    assert response.url == reverse("preview")

    response = client.get(reverse("preview"))
    assert response.status_code == 200
    assert b"Push Day" in response.content
    assert b"Missing" not in response.content

    response = client.post(
        reverse("preview"),
        {
            "import_id": response.context["import_id"],
            "fingerprint": response.context["fingerprint"],
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("history")
    assert WorkoutSession.objects.filter(owner=user).count() == 1
    assert "pending_import_csv" not in client.session


@pytest.mark.django_db
def test_upload_rejects_non_export(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = upload(client, "Date,Workout Name\n2026-01-01,A\n")

    assert response.status_code == 200
    assert b"Missing required CSV headers" in response.content
    assert "pending_import_csv" not in client.session


@pytest.mark.django_db
def test_upload_reports_csv_reader_error(client, small_field_limit):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = upload(
        client,
        CSV.replace("Bench Press (Barbell)", "Very Long Exercise Name"),
    )

    assert response.status_code == 200
    assert b"Invalid CSV" in response.content
    assert "pending_import_csv" not in client.session


@pytest.mark.django_db
def test_corrections_are_owner_scoped(client):
    alice = get_user_model().objects.create_user(username="alice", password="x")
    bob = get_user_model().objects.create_user(username="bob", password="x")
    import_workouts_csv(alice, CSV)
    import_workouts_csv(bob, CSV)
    client.force_login(alice)

    response = client.post(
        reverse("corrections"),
        {"exercise_name": "Chest Fly", "muscle_group": "Core"},
    )

    assert response.status_code == 302
    assert ExerciseMeta.objects.get(owner=alice, exercise_name="Chest Fly").muscle_group == "Core"
    assert ExerciseMeta.objects.get(owner=bob, exercise_name="Chest Fly").muscle_group != "Core"


@pytest.mark.django_db
def test_token_creation_and_revocation_are_owner_scoped(client):
    alice = get_user_model().objects.create_user(username="alice", password="x")
    bob = get_user_model().objects.create_user(username="bob", password="x")
    client.force_login(alice)

    response = client.post(reverse("tokens"), {"name": "reader"})

    assert response.status_code == 200
    secret = response.context["secret"]
    token = ApiToken.objects.get(owner=alice)
    assert token.name == "reader"
    assert token.key_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert token.prefix == secret[:8]
    assert b"Secret:" in response.content

    client.force_login(bob)
    client.post(reverse("revoke_token", args=[token.pk]))
    token.refresh_from_db()
    assert token.revoked_at is None

    client.force_login(alice)
    client.post(reverse("revoke_token", args=[token.pk]))
    token.refresh_from_db()
    assert token.revoked_at is not None


@pytest.mark.django_db
def test_history_renders_imported_sets(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, CSV)
    client.force_login(user)

    response = client.get(reverse("history"))

    assert response.status_code == 200
    assert b"Chest Fly" in response.content
    assert b"Bench Press (Barbell)" in response.content


@pytest.mark.django_db
def test_history_prefetches_exercises(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    import_workouts_csv(user, CSV)
    with CaptureQueriesContext(connection) as baseline:
        client.get(reverse("history"))

    larger_csv = CSV + "\n".join(
        f"2026-01-05 09:{minute:02d}:00,Push Day #1,54m,Exercise {minute},1,80,5,0,0,8"
        for minute in range(10, 40)
    )
    import_workouts_csv(user, larger_csv)
    with CaptureQueriesContext(connection) as grown:
        response = client.get(reverse("history"))

    assert response.status_code == 200
    assert len(grown) == len(baseline)


@pytest.mark.django_db
def test_stale_preview_cannot_import_a_different_file(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    upload(client)
    preview = client.get(reverse("preview"))
    stale_id = preview.context["import_id"]
    stale_fingerprint = preview.context["fingerprint"]

    other_csv = CSV.replace("Push Day #1", "Pull Day").replace(
        "Bench Press (Barbell)", "Seated Row (Cable)"
    )
    upload(client, other_csv)
    response = client.post(
        reverse("preview"),
        {"import_id": stale_id, "fingerprint": stale_fingerprint},
    )

    assert response.status_code == 302
    assert response.url == reverse("upload")
    assert WorkoutSession.objects.filter(owner=user).count() == 0


@pytest.mark.django_db
def test_duplicate_token_name_returns_form_error(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    client.post(reverse("tokens"), {"name": "reader"})
    response = client.post(reverse("tokens"), {"name": "reader"})

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert ApiToken.objects.filter(owner=user).count() == 1

    token = ApiToken.objects.get(owner=user)
    client.post(reverse("revoke_token", args=[token.pk]))
    response = client.post(reverse("tokens"), {"name": "reader"})
    assert response.status_code == 200
    assert b"already exists" in response.content


@pytest.mark.django_db
def test_login_without_next_redirects_to_history(client):
    get_user_model().objects.create_user(username="alice", password="secret")

    response = client.post(reverse("login"), {"username": "alice", "password": "secret"})

    assert response.status_code == 302
    assert response.url == reverse("history")
