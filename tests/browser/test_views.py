import hashlib

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

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

    response = client.post(reverse("preview"))
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
