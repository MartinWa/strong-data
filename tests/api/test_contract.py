import hashlib

import pytest
from django.contrib.auth import get_user_model

from api.contract import CONTRACT_VERSION
from workouts.models import ApiToken

BASE = "/api/v1"


def test_envelope_and_healthz(auth, client):
    health = client.get(BASE + "/healthz", HTTP_AUTHORIZATION="")
    assert health.status_code == 200
    assert health.json() == {
        "contract_version": CONTRACT_VERSION,
        "generated_at": health.json()["generated_at"],
        "status": "ok",
    }
    assert health["Cache-Control"] == "no-store"

    me = auth.get(BASE + "/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert isinstance(me.json()["id"], int)


def test_reference_values(auth):
    assert auth.get(BASE + "/programs").json()["items"] == ["Pull Day", "Push Day"]
    assert auth.get(BASE + "/exercises").json()["items"] == [
        "Bench Press (Barbell)",
        "Chest Fly",
        "Overhead Press",
        "Pull Up",
        "Seated Row (Cable)",
    ]
    assert auth.get(BASE + "/muscle-groups").json()["items"] == [
        "Chest",
        "Lats",
        "Shoulders",
        "Upper Back",
    ]


def test_summary(auth):
    body = auth.get(BASE + "/summary").json()
    assert body["sessions"] == 3
    assert body["sets"] == 7
    assert body["volume_kg"] == 1992.5
    assert body["volume_t"] == 1.99
    assert body["hours"] == 2.68
    assert body["sessions_per_week"] == 0.72
    assert body["avg_volume_per_session"] == 664.17
    assert body["avg_session_min"] == 53.67
    assert isinstance(body["days_since_last_session"], int)

    filtered = auth.get(BASE + "/summary?program=Push Day&start=2026-02-01&end=2026-02-28").json()
    assert filtered["sessions"] == 1
    assert filtered["volume_kg"] == 745.0


def test_series_volume_and_moving_average(auth):
    body = auth.get(BASE + "/series/volume?bucket=week").json()
    assert body["bucket"] == "week"
    assert body["group_by"] is None
    assert [item["bucket_start"] for item in body["items"]] == [
        "2026-01-05",
        "2026-01-12",
        "2026-01-19",
        "2026-01-26",
        "2026-02-02",
    ]
    assert [item["value"] for item in body["items"]] == [1247.5, 0.0, 0.0, 0.0, 745.0]
    assert all(item["groups"] is None for item in body["items"])
    assert all(item["value_4wma"] is None for item in body["items"])

    grouped = auth.get(BASE + "/series/volume?bucket=week&group_by=muscle").json()
    first = grouped["items"][0]
    assert {group["key"]: group["value"] for group in first["groups"]} == {
        "Chest": 647.5,
        "Lats": 0.0,
        "Shoulders": 0.0,
        "Upper Back": 600.0,
    }

    averaged = auth.get(BASE + "/series/volume?bucket=week&moving_average=true").json()
    values = [item["value_4wma"] for item in averaged["items"]]
    assert values[:3] == [None, None, None]
    assert values[3:] == [311.88, 186.25]


def test_series_other_metrics(auth):
    sessions = auth.get(BASE + "/series/sessions?bucket=month&group_by=program").json()
    assert [item["value"] for item in sessions["items"]] == [2, 1]
    assert all(item["groups"] is not None for item in sessions["items"])

    per_session = auth.get(BASE + "/series/volume-per-session?bucket=month").json()
    assert [item["value"] for item in per_session["items"]] == [623.75, 745.0]

    training = auth.get(BASE + "/series/training-time?bucket=month").json()
    assert [item["value"] for item in training["items"]] == [1.93, 0.75]


def test_breakdowns(auth):
    weekday = auth.get(BASE + "/breakdown/weekday").json()["items"]
    assert [row["key"] for row in weekday] == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    monday = weekday[0]
    assert (monday["sessions"], monday["sets"], monday["volume_kg"]) == (2, 5, 1392.5)

    program = auth.get(BASE + "/breakdown/program").json()["items"]
    assert [(row["key"], row["volume_kg"]) for row in program] == [
        ("Push Day", 1392.5),
        ("Pull Day", 600.0),
    ]

    muscle = auth.get(BASE + "/breakdown/muscle").json()["items"]
    assert [(row["key"], row["sets"]) for row in muscle] == [
        ("Chest", 4),
        ("Upper Back", 1),
        ("Shoulders", 1),
        ("Lats", 1),
    ]

    exercises = auth.get(BASE + "/breakdown/exercises?limit=1").json()
    assert exercises["count"] == 1
    assert exercises["items"][0]["key"] == "Bench Press (Barbell)"


def test_exercise_endpoints(auth):
    name = "Bench%20Press%20(Barbell)"
    progress = auth.get(BASE + f"/exercises/{name}/progress").json()["items"]
    assert progress == [
        {
            "date": "2026-01-05",
            "best_est_1rm_kg": 93.33,
            "top_weight_kg": 82.5,
            "max_reps": 5,
            "volume_kg": 647.5,
        },
        {
            "date": "2026-02-02",
            "best_est_1rm_kg": 99.17,
            "top_weight_kg": 85.0,
            "max_reps": 5,
            "volume_kg": 425.0,
        },
    ]

    records = auth.get(BASE + f"/exercises/{name}/records").json()["items"]
    assert [(row["reps"], row["top_weight_kg"]) for row in records] == [(3, 82.5), (5, 85.0)]

    sets = auth.get(BASE + f"/exercises/{name}/sets").json()
    assert sets["count"] == 3
    assert all(row["exercise"] == "Bench Press (Barbell)" for row in sets["items"])


def test_records(auth):
    est = auth.get(BASE + "/records/est-1rm").json()["items"]
    assert [(row["exercise"], row["est_1rm_kg"]) for row in est] == [
        ("Bench Press (Barbell)", 99.17),
        ("Seated Row (Cable)", 80.0),
        ("Overhead Press", 50.67),
    ]
    assert "Chest Fly" not in {row["exercise"] for row in est}

    bodyweight = auth.get(BASE + "/records/bodyweight").json()["items"]
    assert {row["exercise"] for row in bodyweight} == {"Chest Fly", "Pull Up"}
    assert all(row["reps"] == 0 for row in bodyweight)


def test_yearly_and_pace(auth):
    yearly = auth.get(BASE + "/yearly").json()
    assert yearly["items"] == [
        {
            "year": 2026,
            "sessions": 3,
            "sets": 7,
            "volume_kg": 1992.5,
            "volume_t": 1.99,
            "hours": 2.68,
        }
    ]

    pace = auth.get(BASE + "/yearly/pace?year=2026&as_of=2026-03-01").json()
    assert pace["year"] == 2026
    assert pace["ytd"]["sessions"] == 3
    assert pace["last_year_to_date"]["sessions"] == 0
    assert pace["projected"]["sessions"] == 18.25
    assert pace["projected"]["volume_kg"] == 12121.04
    assert pace["needed_per_week"]["volume_kg"] == 0.0
    assert pace["pace"][0]["cumulative_volume_kg"] == 1992.5


def test_raw_sessions_filters_and_detail(auth, alice, bob, client):
    sessions = auth.get(BASE + "/sessions").json()
    assert [row["workout_name"] for row in sessions["items"]] == [
        "Push Day #1",
        "Pull Day #2",
        "Push Day #2",
    ]
    first_id = sessions["items"][0]["id"]

    assert auth.get(BASE + "/sessions?program=Push Day").json()["count"] == 2
    assert auth.get(BASE + "/sessions?exercise=Bench%20Press%20(Barbell)").json()["count"] == 2
    assert auth.get(BASE + "/sessions?muscle=Chest").json()["count"] == 2
    assert auth.get(BASE + "/sessions?weighted=true").json()["count"] == 3
    assert auth.get(BASE + "/sessions?weighted=false").json()["count"] == 0

    detail = auth.get(BASE + f"/sessions/{first_id}").json()
    assert detail["workout_name"] == "Push Day #1"
    assert len(detail["sets"]) == 3
    assert detail["sets"][0]["muscle_group"] == "Chest"

    other = client.get(
        BASE + f"/sessions/{first_id}", HTTP_AUTHORIZATION="Bearer synthetic-token-for-bob"
    )
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "not_found"


def test_raw_sets_filters_and_sort(auth):
    sets = auth.get(BASE + "/sets").json()
    assert sets["count"] == 7
    assert auth.get(BASE + "/sets?weighted=false").json()["count"] == 2
    assert auth.get(BASE + "/sets?muscle=Chest").json()["count"] == 4
    assert auth.get(BASE + "/sets?program=Pull Day").json()["count"] == 2

    descending = auth.get(BASE + "/sets?sort=-volume").json()["items"]
    assert descending[0]["volume_kg"] == 600.0
    assert [row["volume_kg"] for row in descending][-2:] == [0.0, 0.0]

    exercise = auth.get(BASE + "/sets?exercise=Seated%20Row%20(Cable)").json()
    assert exercise["count"] == 1
    assert exercise["items"][0]["rpe"] == 9.0


@pytest.mark.django_db
def test_empty_owner_gets_empty_but_valid_responses(client):
    secret = "empty-owner-secret"
    user = get_user_model().objects.create_user(username="empty", password="x")
    ApiToken.objects.create(
        owner=user,
        name="reader",
        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        prefix=secret[:8],
    )
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {secret}"

    assert client.get(BASE + "/summary").json()["sessions"] == 0
    assert client.get(BASE + "/series/volume").json()["items"] == []
    assert client.get(BASE + "/sets").json()["count"] == 0
    assert client.get(BASE + "/yearly/pace").json()["pace"] == []
    assert client.get(BASE + "/records/est-1rm").json()["items"] == []


def test_owner_scoping_every_endpoint(client, bob):
    endpoints = [
        "/programs",
        "/exercises",
        "/muscle-groups",
        "/summary",
        "/series/volume?group_by=muscle",
        "/breakdown/muscle",
        "/records/est-1rm",
        "/records/bodyweight",
        "/yearly",
        "/yearly/pace",
        "/sessions",
        "/sets",
    ]
    headers = {"HTTP_AUTHORIZATION": "Bearer synthetic-token-for-bob"}
    for endpoint in endpoints:
        response = client.get(BASE + endpoint, **headers)
        assert response.status_code == 200, endpoint
        serialized = str(response.json())
        assert "Bench Press" not in serialized, endpoint
        assert "Push Day" not in serialized, endpoint
        assert "Chest Fly" not in serialized, endpoint

    assert client.get(BASE + "/programs", **headers).json()["items"] == ["Secret Session"]
    assert client.get(BASE + "/exercises", **headers).json()["items"] == ["Squat (Barbell)"]
    assert client.get(BASE + "/sessions", **headers).json()["count"] == 1
