from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tests.api.conftest import CSV
from workouts.services import import_workouts_csv

BASE = "/api/v1"


class ConsumerClient:
    def __init__(self, client, secret):
        self.client = client
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}

    def get(self, path, **extra):
        full_path = path if path.startswith(BASE) else BASE + path
        return self.client.get(full_path, **{**self.headers, **extra})

    def json(self, path):
        response = self.get(path)
        assert response.status_code == 200, (path, response.content[:300])
        assert response["Cache-Control"] == "no-store"
        return response.json()

    def all_pages(self, path):
        items = []
        current = path
        seen = set()
        while current:
            assert current not in seen, "pagination loop"
            seen.add(current)
            page = self.json(current)
            assert set(page) >= {
                "contract_version",
                "generated_at",
                "items",
                "count",
                "next",
                "previous",
                "has_more",
            }
            items.extend(page["items"])
            current = page["next"]
        assert len(items) == page["count"]
        return items


@pytest.mark.django_db
def test_consumer_can_discover_and_page_through_data(client):
    user = get_user_model().objects.create_user(username="consumer", password="x")
    import_workouts_csv(user, CSV)
    client.force_login(user)
    response = client.post(reverse("tokens"), {"name": "consumer-reader"})
    assert response.status_code == 200
    secret = response.context["secret"]
    assert secret

    api = ConsumerClient(client, secret)

    assert api.json("/me")["username"] == "consumer"
    assert api.json("/healthz")["status"] == "ok"

    programs = api.json("/programs")["items"]
    exercises = api.json("/exercises")["items"]
    assert programs and exercises

    sets = api.all_pages("/sets?limit=2")
    assert len(sets) == 7
    assert {row["exercise"] for row in sets} == set(exercises)

    sessions = api.all_pages("/sessions?limit=1")
    assert len(sessions) == 3
    for session in sessions:
        detail = api.json(f"/sessions/{session['id']}")
        assert detail["set_count"] == len(detail["sets"])

    for exercise in exercises:
        encoded = quote(exercise, safe="")
        assert api.json(f"/exercises/{encoded}/progress")["count"] >= 1
        assert api.json(f"/exercises/{encoded}/records")["count"] >= 1
        assert isinstance(api.all_pages(f"/exercises/{encoded}/sets?limit=3"), list)

    for path in [
        "/summary",
        "/series/sessions",
        "/series/volume",
        "/series/volume-per-session",
        "/series/training-time",
        "/breakdown/weekday",
        "/breakdown/program",
        "/breakdown/muscle",
        "/breakdown/exercises",
        "/records/est-1rm",
        "/records/bodyweight",
        "/yearly",
        "/yearly/pace",
    ]:
        body = api.json(path)
        assert body["contract_version"] == "1.0"
        assert "generated_at" in body

    assert api.get("/summary", HTTP_AUTHORIZATION="").status_code == 401
