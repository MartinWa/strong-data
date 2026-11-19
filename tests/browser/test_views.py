import csv
import hashlib
import os
import re
import time
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

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


@pytest.fixture(autouse=True)
def pending_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STRONG_PENDING_DIR", str(tmp_path / "pending"))


@pytest.fixture
def small_field_limit():
    original = csv.field_size_limit()
    csv.field_size_limit(13)
    yield
    csv.field_size_limit(original)


@pytest.mark.django_db
def test_footer_shows_version_and_github_links(client):
    response = client.get(reverse("login"))
    content = response.content.decode()

    assert response.status_code == 200
    assert app_version() in content
    assert 'href="https://github.com/' in content
    assert "/api/v1/docs" not in content
    assert "/api/v1/healthz" not in content
    assert "api-reference" not in content


@pytest.mark.django_db
def test_footer_links_api_reference_when_logged_in(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert '<a href="/api/v1/docs">API reference</a>' in content
    assert "/api/v1/healthz" not in content


def test_footer_version_links_to_releases(client):
    content = client.get(reverse("login")).content.decode()

    assert re.search(rf'<a href="[^"]*/releases[^"]*"[^>]*>\s*{re.escape(app_version())}', content)


def test_password_toggle_is_an_icon_button(client):
    content = client.get(reverse("login")).content.decode()

    assert 'class="password-toggle"' in content
    assert 'aria-label="Show password"' in content
    assert '<div class="password-field">' in content
    assert content.index('class="password-field"') < content.index('class="password-toggle"')
    assert "<svg" in content
    assert ">Show<" not in content


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["upload", "sessions", "corrections", "tokens"])
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
    assert response.url == reverse("sessions")
    assert WorkoutSession.objects.filter(owner=user).count() == 1
    assert "pending_import" not in client.session


@pytest.mark.django_db
def test_upload_rejects_non_export(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = upload(client, "Date,Workout Name\n2026-01-01,A\n")

    assert response.status_code == 200
    assert b"Missing required CSV headers" in response.content
    assert "pending_import" not in client.session


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
    assert "pending_import" not in client.session


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
def test_sessions_renders_imported_sets(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, CSV)
    client.force_login(user)

    response = client.get(reverse("sessions"))

    assert response.status_code == 200
    assert b"Chest Fly" in response.content
    assert b"Bench Press (Barbell)" in response.content


@pytest.mark.django_db
def test_sessions_prefetches_exercises(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    import_workouts_csv(user, CSV)
    with CaptureQueriesContext(connection) as baseline:
        client.get(reverse("sessions"))

    larger_csv = CSV + "\n".join(
        f"2026-01-05 09:{minute:02d}:00,Push Day #1,54m,Exercise {minute},1,80,5,0,0,8"
        for minute in range(10, 40)
    )
    import_workouts_csv(user, larger_csv)
    with CaptureQueriesContext(connection) as grown:
        response = client.get(reverse("sessions"))

    assert response.status_code == 200
    assert len(grown) == len(baseline)


MULTI_SESSION_CSV = (
    "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
    "2026-01-05 09:00:00,Push Day #1,54m,Bench Press (Barbell),1,80,5,0,0,8.0\n"
    "2026-02-10 18:00:00,Pull Day,47m,Barbell Row,1,60,8,0,0,\n"
    "2026-03-20 07:30:00,Leg Day,62m,Back Squat,1,100,5,0,0,9.0\n"
)


@pytest.mark.django_db
def test_legacy_history_url_redirects_to_sessions(client):
    response = client.get("/history/")

    assert response.status_code == 301
    assert response.url == "/sessions/"


@pytest.mark.django_db
def test_sessions_empty_state_prompts_upload(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = client.get(reverse("sessions"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "No sessions yet." in content
    assert "Upload a Strong CSV export to see your workouts here." in content
    assert 'href="/upload/"' in content
    assert 'aria-label="Filter sessions"' not in content


@pytest.mark.django_db
def test_sessions_rows_are_collapsed_details(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, CSV)
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert '<details class="card session">' in content
    assert '<summary class="session-head">' in content
    assert '<details class="card session" open' not in content
    assert "Bench Press (Barbell)" in content


@pytest.mark.django_db
def test_sessions_filter_by_program(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    response = client.get(reverse("sessions"), {"program": "Pull Day"})

    assert response.context["page"].paginator.count == 1
    assert b"Barbell Row" in response.content
    assert b"Back Squat" not in response.content
    assert b'value="Pull Day" selected' in response.content


@pytest.mark.django_db
def test_sessions_filter_by_date_range(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    in_range = client.get(reverse("sessions"), {"from": "2026-02-01", "to": "2026-02-28"})
    invalid = client.get(reverse("sessions"), {"from": "not-a-date"})

    assert in_range.context["page"].paginator.count == 1
    assert b"Barbell Row" in in_range.content
    assert b"Back Squat" not in in_range.content
    assert invalid.context["page"].paginator.count == 3


@pytest.mark.django_db
def test_sessions_search_matches_workout_or_exercise(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    by_exercise = client.get(reverse("sessions"), {"q": "squat"})
    by_workout = client.get(reverse("sessions"), {"q": "pull"})

    assert by_exercise.context["page"].paginator.count == 1
    assert b"Back Squat" in by_exercise.content
    assert by_workout.context["page"].paginator.count == 1
    assert b"Barbell Row" in by_workout.content


@pytest.mark.django_db
def test_sessions_no_match_state_offers_clear(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    content = client.get(reverse("sessions"), {"q": "deadlift"}).content.decode()

    assert "No sessions match these filters." in content
    assert "Clear filters" in content
    assert "No sessions yet." not in content


@pytest.mark.django_db
def test_sessions_pager_keeps_filters(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    rows = "\n".join(
        f"2026-01-{day:02d} 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8" for day in range(1, 31)
    )
    import_workouts_csv(user, CSV.splitlines()[0] + "\n" + rows + "\n")

    content = client.get(reverse("sessions"), {"q": "Bench"}).content.decode()

    assert "?q=Bench&amp;page=2" in content or "?q=Bench&page=2" in content


@pytest.mark.django_db
def test_sessions_filters_apply_without_submit_by_default(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert "data-filter-form" in content
    assert 'src="/static/workouts/filters.js"' in content
    assert 'type="submit">Filter</button>' in content


@pytest.mark.django_db
def test_sessions_clear_button_always_rendered(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    unfiltered = client.get(reverse("sessions")).content.decode()
    filtered = client.get(reverse("sessions"), {"q": "squat"}).content.decode()

    assert 'href="/sessions/">Clear</a>' in unfiltered
    assert 'href="/sessions/">Clear</a>' in filtered


@pytest.mark.django_db
def test_sessions_badges_pluralize_and_trim_volume(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, MULTI_SESSION_CSV)
    client.force_login(user)

    content = client.get(reverse("sessions"), {"q": "pull"}).content.decode()

    assert ">1 set<" in content
    assert ">1 sets<" not in content
    assert ">480 kg<" in content
    assert "480.00 kg" not in content


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
def test_login_without_next_redirects_to_sessions(client):
    get_user_model().objects.create_user(username="alice", password="secret")

    response = client.post(reverse("login"), {"username": "alice", "password": "secret"})

    assert response.status_code == 302
    assert response.url == reverse("sessions")


@pytest.mark.django_db
def test_pending_csv_is_not_stored_in_the_session(client, tmp_path):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    upload(client)

    stored = client.session["pending_import"]
    assert set(stored) == {"id", "fingerprint", "created_at"}
    assert (tmp_path / "pending" / f"{stored['id']}.csv").is_file()
    assert (tmp_path / "pending" / f"{stored['id']}.json").is_file()


@pytest.mark.django_db
def test_preview_shows_a_summary_and_a_bounded_sample(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    rows = "\n".join(
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,8"
        for minute in range(30)
    )
    upload(client, CSV.splitlines()[0] + "\n" + rows + "\n")

    response = client.get(reverse("preview"))

    assert response.status_code == 200
    assert b"The first 20 of 30 sets" in response.content
    assert b"Exercise 00" in response.content
    assert b"Exercise 29" not in response.content


@pytest.mark.django_db
def test_expired_preview_redirects_to_upload(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    upload(client)
    session = client.session
    session["pending_import"]["created_at"] -= 7200
    session.save()

    response = client.get(reverse("preview"))

    assert response.status_code == 302
    assert response.url == reverse("upload")
    assert "pending_import" not in client.session


@pytest.mark.django_db
def test_sessions_paginates_sessions(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    rows = "\n".join(
        f"2026-01-{day:02d} 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8" for day in range(1, 31)
    )
    import_workouts_csv(user, CSV.splitlines()[0] + "\n" + rows + "\n")

    first = client.get(reverse("sessions"))
    second = client.get(reverse("sessions") + "?page=2")

    assert first.context["page"].paginator.num_pages == 2
    assert len(first.context["page"].object_list) == 25
    assert len(second.context["page"].object_list) == 5
    assert (
        first.context["page"].object_list[0].session_date
        > second.context["page"].object_list[0].session_date
    )
    assert b'href="?page=2">Older</a>' in first.content
    assert "Sessions" in first.content.decode()
    assert "Import history" not in first.content.decode()


@pytest.mark.django_db
def test_token_expiry_can_be_set_and_must_be_in_the_future(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = client.post(reverse("tokens"), {"name": "reader", "expires_at": "2030-01-01T00:00"})
    assert response.status_code == 200
    assert ApiToken.objects.get(owner=user).expires_at is not None

    response = client.post(reverse("tokens"), {"name": "stale", "expires_at": "2000-01-01T00:00"})
    assert response.status_code == 200
    assert b"future" in response.content
    assert not ApiToken.objects.filter(owner=user, name="stale").exists()


@pytest.mark.django_db
def test_muscle_group_accepts_free_text(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, CSV)
    client.force_login(user)

    response = client.post(
        reverse("corrections"),
        {"exercise_name": "Chest Fly", "muscle_group": "Forearms"},
    )

    assert response.status_code == 302
    meta = ExerciseMeta.objects.get(owner=user, exercise_name="Chest Fly")
    assert meta.muscle_group == "Forearms"


@pytest.mark.django_db
def test_oversized_upload_is_rejected_before_the_file_is_read(client):
    from django.test import RequestFactory

    from workouts.views import MAX_UPLOAD_BYTES, upload

    user = get_user_model().objects.create_user(username="alice", password="x")
    request = RequestFactory().post(reverse("upload"), data={})
    request.user = user
    request.META["CONTENT_LENGTH"] = str(MAX_UPLOAD_BYTES + 2 * 1024 * 1024)

    response = upload(request)

    assert response.status_code == 200
    assert b"CSV export must be 10 MB or smaller." in response.content


@pytest.mark.django_db
def test_token_list_marks_an_expired_token(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    ApiToken.objects.create(
        owner=user,
        name="stale",
        key_hash=hashlib.sha256(b"stale-secret").hexdigest(),
        prefix="stale-se",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    content = client.get(reverse("tokens")).content.decode()

    assert ">expired</span>" in content
    assert "badge-success" not in content


@pytest.mark.django_db
def test_field_hints_and_errors_are_referenced_by_the_input(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("tokens")).content.decode()

    assert 'aria-describedby="id_expires_at_helptext"' in content
    assert 'id="id_expires_at_helptext"' in content


@pytest.mark.django_db
def test_login_errors_are_referenced_by_the_password_field(client):
    get_user_model().objects.create_user(username="alice", password="synthetic-password-1")

    content = client.post(reverse("login"), {"username": "alice", "password": ""}).content.decode()

    assert 'aria-describedby="id_password_error"' in content
    assert 'id="id_password_error"' in content


@pytest.mark.django_db
def test_token_list_shows_the_expiry(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    client.post(reverse("tokens"), {"name": "reader", "expires_at": "2030-01-01T00:00"})

    response = client.get(reverse("tokens"))

    assert b"expires 2030-01-01 00:00" in response.content


@pytest.mark.django_db
def test_preview_sweeps_expired_pending_files(client, tmp_path):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    upload(client)
    stored = client.session["pending_import"]
    expired = time.time() - 7200
    for suffix in ("csv", "json"):
        os.utime(tmp_path / "pending" / f"{stored['id']}.{suffix}", (expired, expired))

    response = client.get(reverse("preview"))

    assert response.status_code == 302
    assert response.url == reverse("upload")
    assert list((tmp_path / "pending").iterdir()) == []


@pytest.mark.django_db
def test_login_page_offers_remember_me_and_a_password_toggle(client):
    response = client.get(reverse("login"))
    body = response.content.decode()

    assert 'name="remember_me"' in body
    assert "data-password-toggle" in body
    assert "There is no open registration." in body


@pytest.mark.django_db
def test_login_without_remember_me_expires_the_session_at_browser_close(client):
    get_user_model().objects.create_user(username="alice", password="synthetic-pass-123")

    response = client.post(
        reverse("login"),
        {"username": "alice", "password": "synthetic-pass-123"},
    )

    assert response.status_code == 302
    assert client.session.get_expire_at_browser_close() is True


@pytest.mark.django_db
def test_login_with_remember_me_keeps_the_configured_session_age(client):
    get_user_model().objects.create_user(username="alice", password="synthetic-pass-123")

    response = client.post(
        reverse("login"),
        {"username": "alice", "password": "synthetic-pass-123", "remember_me": "on"},
    )

    assert response.status_code == 302
    assert client.session.get_expire_at_browser_close() is False
