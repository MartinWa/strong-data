import hashlib
from datetime import UTC, date, datetime, time
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

import api.auth as auth_module
from api.queries import SESSION_SORT_KEYS, SET_SORT_KEYS
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


@pytest.mark.django_db
def test_pace_reads_all_totals_in_one_transaction(auth):
    with CaptureQueriesContext(connection) as captured:
        response = auth.get(BASE + "/yearly/pace?year=2026&as_of=2026-03-01")

    assert response.status_code == 200
    sql = [query["sql"].lower() for query in captured.captured_queries]
    reads = [i for i, query in enumerate(sql) if 'from "workouts_workoutsession"' in query]
    assert len(reads) == 4
    assert any(query.startswith("savepoint") and i < reads[0] for i, query in enumerate(sql))
    assert not any(
        query.startswith("release savepoint") and reads[0] < i < reads[-1]
        for i, query in enumerate(sql)
    )
    assert any(
        query.startswith("release savepoint") and i > reads[-1] for i, query in enumerate(sql)
    )


@pytest.mark.django_db
def test_one_sided_series_ranges_are_capped(client):
    user = make_token_user(client, "longrange", "longrange-secret")
    make_session(user, date(2010, 1, 1), "Old")
    make_session(user, date(2026, 1, 1), "Recent")

    assert_error(
        client.get(BASE + "/series/sessions?bucket=day&start=2010-01-01"), 422, "validation_error"
    )
    assert_error(
        client.get(BASE + "/series/sessions?bucket=day&end=2026-01-01"), 422, "validation_error"
    )


@pytest.mark.django_db
def test_short_one_sided_series_range_is_allowed(client):
    user = make_token_user(client, "shortrange", "shortrange-secret")
    make_session(user, date(2026, 1, 1), "One")
    make_session(user, date(2026, 1, 2), "Two")

    body = client.get(BASE + "/series/sessions?bucket=day&start=2026-01-01").json()

    assert body["count"] == 2


@pytest.mark.django_db
def test_raw_pagination_is_applied_in_the_database(auth):
    with CaptureQueriesContext(connection) as captured:
        response = auth.get(BASE + "/sets?limit=1")

    assert response.status_code == 200
    assert response.json()["count"] == 7
    sql = [query["sql"].lower() for query in captured.captured_queries]
    paged = [query for query in sql if 'from "workouts_workoutset"' in query and "limit 1" in query]
    assert paged
    assert all("order by" in query for query in paged)


@pytest.mark.django_db
def test_authentication_failures_follow_the_error_contract(client, monkeypatch):
    def fail_with(message):
        def fail(*args, **kwargs):
            raise OperationalError(message)

        return fail

    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {SECRET}"
    monkeypatch.setattr(auth_module.ApiToken.objects, "filter", fail_with("database is locked"))

    for path in ("/me", "/openapi.json", "/"):
        assert_error(client.get(BASE + path), 503, "service_unavailable")

    monkeypatch.setattr(
        auth_module.ApiToken.objects,
        "filter",
        fail_with("no such table: workouts_apitoken"),
    )
    assert_error(client.get(BASE + "/openapi.json"), 500, "internal_error")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("bucket", "expected"),
    [
        ("day", "9999-12-31"),
        ("week", "9999-12-27"),
        ("month", "9999-12-01"),
        ("year", "9999-01-01"),
    ],
)
def test_final_date_bucket_does_not_overflow(auth, bucket, expected):
    response = auth.get(BASE + f"/series/volume?bucket={bucket}&start=9999-12-31&end=9999-12-31")

    assert response.status_code == 200, response.content[:300]
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["bucket_start"] == expected


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(SESSION_SORT_KEYS))
def test_every_session_sort_key_works_in_database(auth, key):
    for sort in (key, f"-{key}"):
        response = auth.get(BASE + f"/sessions?sort={sort}")
        assert response.status_code == 200, (sort, response.content[:200])


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(SET_SORT_KEYS))
def test_every_set_sort_key_works_in_database(auth, key):
    for sort in (key, f"-{key}"):
        response = auth.get(BASE + f"/sets?sort={sort}")
        assert response.status_code == 200, (sort, response.content[:200])


@pytest.mark.django_db
def test_zero_weight_sets_are_bodyweight_everywhere(client):
    user = make_token_user(client, "bodyweight", "bodyweight-secret")
    csv = (
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-01-05 09:00:00,Push,30m,Push Up,1,0,20,0,0,\n"
        "2026-01-05 09:05:00,Push,30m,Bench Press,1,80,5,0,0,\n"
    )
    import_workouts_csv(user, csv)

    bodyweight = client.get(BASE + "/records/bodyweight").json()
    assert [row["exercise"] for row in bodyweight["items"]] == ["Push Up"]

    unweighted = client.get(BASE + "/sets?weighted=false").json()
    assert [row["exercise"] for row in unweighted["items"]] == ["Push Up"]

    weighted = client.get(BASE + "/sets?weighted=true").json()
    assert [row["exercise"] for row in weighted["items"]] == ["Bench Press"]


@pytest.mark.django_db
def test_deleting_all_sessions_clears_the_exercise_reference(client):
    user = make_token_user(client, "deleted", "deleted-secret")
    csv = (
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-01-05 09:00:00,Push,30m,Bench Press,1,80,5,0,0,\n"
        "2026-01-05 09:05:00,Push,30m,Chest Fly,1,20,12,0,0,\n"
    )
    import_workouts_csv(user, csv)
    assert client.get(BASE + "/exercises").json()["items"] == ["Bench Press", "Chest Fly"]

    client.force_login(user)
    client.post(reverse("delete_sessions"))

    assert client.get(BASE + "/exercises").json()["items"] == []


@pytest.mark.django_db
def test_disallowed_host_returns_the_json_error_envelope(client):
    response = client.get(BASE + "/healthz", HTTP_HOST="not-allowed.example")

    assert response.status_code == 400
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["contract_version"] == "1.0"
    assert body["error"]["code"] == "bad_request"
