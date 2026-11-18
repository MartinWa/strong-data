import hashlib
from datetime import UTC, date, datetime, time
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.api.conftest import SECRET
from tests.api.test_guards import assert_error
from workouts.models import ApiToken, WorkoutSession
from workouts.services import import_workouts_csv

BASE = "/api/v1"


def make_session(user, day, name, *, duration_min=60, volume="0"):
    return WorkoutSession.objects.create(
        owner=user,
        session_date=day,
        program="Test",
        workout_name=name,
        start_time=timezone.make_aware(datetime.combine(day, time(9, 0)), UTC),
        duration_min=duration_min,
        set_count=1,
        total_volume_kg=volume,
    )


def make_token_user(client, username, secret):
    user = get_user_model().objects.create_user(username=username, password="x")
    ApiToken.objects.create(
        owner=user,
        name="reader",
        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        prefix=secret[:8],
    )
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {secret}"
    return user


@pytest.mark.django_db
def test_pace_normalizes_cutoff_to_selected_year(client):
    user = make_token_user(client, "pace", "pace-secret")
    make_session(user, date(2024, 2, 15), "Early 2024")
    make_session(user, date(2024, 6, 15), "Late 2024")
    make_session(user, date(2025, 2, 15), "Early 2025")
    make_session(user, date(2025, 11, 15), "Late 2025")

    body = client.get(BASE + "/yearly/pace?year=2025&as_of=2026-03-01").json()

    assert body["ytd"]["sessions"] == 1
    assert body["last_year_to_date"]["sessions"] == 1
    assert body["projected"]["sessions"] == 6.08


@pytest.mark.django_db
def test_invalid_years_return_422(auth):
    for year in (-1, 0, 1, 10000):
        assert_error(auth.get(BASE + f"/yearly/pace?year={year}"), 422, "validation_error")


@pytest.mark.django_db
def test_projection_keeps_precision_until_final_response(client):
    user = make_token_user(client, "precision", "precision-secret")
    make_session(user, date(2026, 1, 1), "One minute", duration_min=1)

    body = client.get(BASE + "/yearly/pace?year=2026&as_of=2026-01-01").json()

    assert body["ytd"]["hours"] == 0.02
    assert body["projected"]["hours"] == 6.08


@pytest.mark.django_db
def test_explicit_empty_series_range_is_zero_filled(auth):
    body = auth.get(BASE + "/series/volume?bucket=week&start=2026-03-02&end=2026-03-15").json()

    assert body["count"] == 2
    assert [item["bucket_start"] for item in body["items"]] == ["2026-03-02", "2026-03-09"]
    assert [item["value"] for item in body["items"]] == [0.0, 0.0]


@pytest.mark.django_db
def test_session_detail_reads_session_and_sets_in_one_transaction(auth, alice):
    session_id = auth.get(BASE + "/sessions").json()["items"][0]["id"]

    with CaptureQueriesContext(connection) as captured:
        response = auth.get(BASE + f"/sessions/{session_id}")

    assert response.status_code == 200
    sql = [query["sql"].lower() for query in captured.captured_queries]
    session_index = next(i for i, q in enumerate(sql) if 'from "workouts_workoutsession"' in q)
    sets_index = next(i for i, q in enumerate(sql) if 'from "workouts_workoutset"' in q)
    assert any(q.startswith("savepoint") and i < session_index for i, q in enumerate(sql))
    assert any(q.startswith("release savepoint") and i > sets_index for i, q in enumerate(sql))
    assert not any(
        q.startswith("release savepoint") and session_index < i < sets_index
        for i, q in enumerate(sql)
    )


@pytest.mark.django_db
def test_exercise_names_with_slashes_are_reachable(client):
    make_token_user(client, "slash", "slash-secret")
    csv = (
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-01-05 09:00:00,Push,30m,Bench/Press,1,80,5,0,0,8.0\n"
    )
    import_workouts_csv(get_user_model().objects.get(username="slash"), csv)
    encoded = quote("Bench/Press", safe="")

    for suffix in ("progress", "records", "sets"):
        response = client.get(BASE + f"/exercises/{encoded}/{suffix}")
        assert response.status_code == 200, (suffix, response.content[:200])
        assert response.json()["count"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/records/est-1rm",
        "/records/bodyweight",
        "/programs",
        "/exercises",
        "/muscle-groups",
        "/me",
        "/yearly",
        "/healthz",
    ],
)
def test_routes_without_query_models_reject_unknown_parameters(client, alice, path):
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {SECRET}"
    assert_error(client.get(BASE + path + "?start=2026-01-01"), 422, "validation_error")


@pytest.mark.django_db
def test_session_detail_rejects_unknown_parameters(auth, alice):
    session_id = auth.get(BASE + "/sessions").json()["items"][0]["id"]
    assert_error(
        auth.get(BASE + f"/sessions/{session_id}?start=2026-01-01"), 422, "validation_error"
    )


@pytest.mark.django_db
def test_unmatched_api_url_returns_json_error_envelope(auth):
    response = auth.get(BASE + "/unknown")

    assert response.status_code == 404
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["contract_version"] == "1.0"
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_openapi_documents_error_responses(auth):
    schema = auth.get(BASE + "/openapi.json").json()

    assert "ErrorOut" in schema["components"]["schemas"]
    error_ref = {"$ref": "#/components/schemas/ErrorOut"}
    for path in ("/api/v1/sessions/{id}", "/api/v1/records/est-1rm", "/api/v1/summary"):
        responses = schema["paths"][path]["get"]["responses"]
        for status in ("401", "404", "422"):
            assert status in responses, (path, status)
            assert responses[status]["content"]["application/json"]["schema"] == error_ref

    health = schema["paths"]["/api/v1/healthz"]["get"]["responses"]
    assert "401" not in health
    assert "422" in health


@pytest.mark.django_db
def test_only_transient_database_errors_are_service_unavailable(auth, monkeypatch):
    import api.routers.reference as reference

    def fail_with(message):
        def fail(*args, **kwargs):
            raise OperationalError(message)

        return fail

    monkeypatch.setattr(reference.WorkoutSession.objects, "filter", fail_with("database is locked"))
    assert_error(auth.get(BASE + "/programs"), 503, "service_unavailable")

    monkeypatch.setattr(
        reference.WorkoutSession.objects,
        "filter",
        fail_with("no such table: workouts_workoutsession"),
    )
    assert_error(auth.get(BASE + "/programs"), 500, "internal_error")
