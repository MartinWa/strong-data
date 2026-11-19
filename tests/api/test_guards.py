import hashlib
from datetime import timedelta

from django.contrib.staticfiles import finders
from django.test import Client
from django.utils import timezone

from tests.api.conftest import SECRET
from workouts.models import ApiToken

BASE = "/api/v1"


def assert_error(response, status, code):
    assert response.status_code == status, response.content[:300]
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["contract_version"] == "1.0"
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body


def test_missing_and_invalid_tokens(auth):
    anonymous = Client()
    missing = anonymous.get(BASE + "/me")
    assert_error(missing, 401, "invalid_credentials")
    assert missing["WWW-Authenticate"] == "Bearer"

    for header in ["Basic abc", "Bearer ", "Bearer wrong-secret"]:
        response = anonymous.get(BASE + "/me", HTTP_AUTHORIZATION=header)
        assert_error(response, 401, "invalid_credentials")

    assert auth.get(BASE + "/me").status_code == 200


def test_revoked_and_expired_tokens(client, alice):
    token = ApiToken.objects.get(owner=alice)
    token.revoked_at = timezone.now()
    token.save()
    assert_error(
        client.get(BASE + "/me", HTTP_AUTHORIZATION=f"Bearer {SECRET}"),
        401,
        "invalid_credentials",
    )

    token.revoked_at = None
    token.expires_at = timezone.now() - timedelta(seconds=1)
    token.save()
    assert_error(
        client.get(BASE + "/me", HTTP_AUTHORIZATION=f"Bearer {SECRET}"),
        401,
        "invalid_credentials",
    )


def test_token_prefix_collision_rejected(alice):
    anonymous = Client()
    decoy = SECRET[:8] + "decoy-secret"
    ApiToken.objects.create(
        owner=alice,
        name="other",
        key_hash=hashlib.sha256(decoy.encode()).hexdigest(),
        prefix=SECRET[:8],
    )
    assert anonymous.get(BASE + "/me", HTTP_AUTHORIZATION=f"Bearer {SECRET}").status_code == 200
    assert anonymous.get(BASE + "/me", HTTP_AUTHORIZATION=f"Bearer {decoy}").status_code == 200

    unknown = SECRET[:8] + "unknown-secret"
    assert_error(
        anonymous.get(BASE + "/me", HTTP_AUTHORIZATION=f"Bearer {unknown}"),
        401,
        "invalid_credentials",
    )


def test_docs_page_requires_token(auth):
    assert_error(Client().get(BASE + "/docs"), 401, "invalid_credentials")
    response = auth.get(BASE + "/docs")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert b"swagger" in response.content.lower()


def test_docs_serve_their_assets_locally(alice):
    session = Client()
    session.force_login(alice)

    content = session.get(BASE + "/docs").content.decode()
    assert "/static/ninja/swagger-ui-bundle.js" in content
    assert "cdn.jsdelivr.net" not in content
    assert finders.find("ninja/swagger-ui-bundle.js")


def test_docs_and_schema_allow_a_logged_in_session(alice):
    session = Client()
    session.force_login(alice)

    docs = session.get(BASE + "/docs")
    assert docs.status_code == 200
    assert docs["Cache-Control"] == "no-store"

    schema = session.get(BASE + "/openapi.json")
    assert schema.status_code == 200
    assert schema["Cache-Control"] == "no-store"
    assert "/api/v1/summary" in schema.json()["paths"]


def test_openapi_requires_token(auth):
    assert_error(Client().get(BASE + "/openapi.json"), 401, "invalid_credentials")
    response = auth.get(BASE + "/openapi.json")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    paths = response.json()["paths"]
    for expected in [
        "/api/v1/healthz",
        "/api/v1/summary",
        "/api/v1/series/volume",
        "/api/v1/exercises/{name}/progress",
        "/api/v1/sessions/{id}",
    ]:
        assert expected in paths


def test_openapi_documents_sort_keys(auth):
    paths = auth.get(BASE + "/openapi.json").json()["paths"]
    sessions = paths["/api/v1/sessions"]["get"]["parameters"]
    sets = paths["/api/v1/sets"]["get"]["parameters"]

    session_sort = next(item for item in sessions if item["name"] == "sort")
    assert (
        "Allowed keys: date, program, sets, start_time, volume, workout_name"
        in (session_sort["description"])
    )
    assert "Default: date" in session_sort["description"]

    set_sort = next(item for item in sets if item["name"] == "sort")
    assert "Default: set_time" in set_sort["description"]
    assert "est_1rm" in set_sort["description"]


def test_method_body_and_media_type_guards(auth):
    anonymous = Client()
    assert_error(auth.post(BASE + "/summary"), 405, "method_not_allowed")
    assert_error(auth.delete(BASE + "/sets"), 405, "method_not_allowed")

    oversized = anonymous.get(
        BASE + "/summary",
        HTTP_AUTHORIZATION=f"Bearer {SECRET}",
        CONTENT_LENGTH=str(10 * 1024 * 1024 + 1),
    )
    assert_error(oversized, 413, "payload_too_large")

    wrong_type = anonymous.generic(
        "GET",
        BASE + "/summary",
        data=b"x",
        content_type="text/plain",
        HTTP_AUTHORIZATION=f"Bearer {SECRET}",
    )
    assert_error(wrong_type, 415, "unsupported_media_type")


def test_unknown_and_repeated_parameters(client, auth):
    assert_error(auth.get(BASE + "/summary?nope=1"), 422, "validation_error")
    assert_error(auth.get(BASE + "/sets?limit=1&limit=2"), 422, "validation_error")
    assert_error(auth.get(BASE + "/sessions?sort=date&sort=-date"), 422, "validation_error")


def test_strict_typed_parameters(client, auth):
    bad_queries = [
        "/sets?limit=50.5",
        "/sets?limit=true",
        "/sets?limit=abc",
        "/sets?offset=-1",
        "/sets?start=2026-1-5",
        "/sets?end=not-a-date",
        "/sessions?weighted=1",
        "/sessions?weighted=yes",
        "/series/volume?bucket=decade",
        "/series/sessions?group_by=muscle",
        "/series/volume?bucket=day&moving_average=true",
        "/sets?sort=unknown",
        "/summary?start=2026-02-01&end=2026-01-01",
        "/summary?start=2010-01-01&end=2020-01-01",
        "/sets?limit=201",
    ]
    for query in bad_queries:
        assert_error(auth.get(BASE + query), 422, "validation_error")


def test_healthz_stays_anonymous():
    response = Client().get(BASE + "/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_root_requires_token(auth):
    assert_error(Client().get(BASE + "/"), 401, "invalid_credentials")
    assert auth.get(BASE + "/").status_code != 401
