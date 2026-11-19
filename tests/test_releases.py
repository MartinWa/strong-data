import json
from io import BytesIO

import pytest
from django.core.cache import cache
from django.urls import reverse

from strong_data import releases


@pytest.fixture(autouse=True)
def clear_release_cache():
    cache.clear()
    yield
    cache.clear()


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


def release_payload(tag, *, draft=False, prerelease=False):
    return json.dumps({"tag_name": tag, "draft": draft, "prerelease": prerelease}).encode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.2.3", (1, 2, 3)),
        ("v1.2.3", (1, 2, 3)),
        ("0.1.0", (0, 1, 0)),
        ("1.2", None),
        ("1.2.3-rc1", None),
        ("01.2.3", None),
        ("", None),
        (None, None),
        (123, None),
        ("1.2.3" + "0" * 40, None),
    ],
)
def test_version_number_accepts_only_stable_tags(value, expected):
    assert releases.version_number(value) == expected


def test_update_available_is_none_when_the_check_is_disabled(settings, monkeypatch):
    settings.UPDATE_CHECK_ENABLED = False
    monkeypatch.setattr(releases, "latest_version", lambda: (9, 9, 9))

    assert releases.update_available() is None


def test_update_available_is_none_for_a_non_release_version(settings, monkeypatch):
    settings.UPDATE_CHECK_ENABLED = True
    monkeypatch.setattr(releases, "app_version", lambda: "development")
    monkeypatch.setattr(releases, "latest_version", lambda: (9, 9, 9))

    assert releases.update_available() is None


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("0.1.0", (0, 1, 1), True),
        ("0.1.0", (0, 2, 0), True),
        ("0.1.0", (0, 1, 0), False),
        ("0.2.0", (0, 1, 9), False),
        ("0.1.0", None, None),
    ],
)
def test_update_available_compares_against_the_latest_release(
    settings, monkeypatch, current, latest, expected
):
    settings.UPDATE_CHECK_ENABLED = True
    monkeypatch.setattr(releases, "app_version", lambda: current)
    monkeypatch.setattr(releases, "latest_version", lambda: latest)

    assert releases.update_available() is expected


def test_latest_version_reads_and_caches_the_github_release(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(release_payload("0.2.0"))

    monkeypatch.setattr(releases, "urlopen", fake_urlopen)

    assert releases.latest_version() == (0, 2, 0)
    assert releases.latest_version() == (0, 2, 0)
    assert calls == [releases.LATEST_RELEASE_API]


@pytest.mark.parametrize(
    "payload",
    [
        release_payload("0.2.0", draft=True),
        release_payload("0.2.0", prerelease=True),
        release_payload("not-a-version"),
        b"not json",
        b"x" * (releases.MAX_RESPONSE_BYTES + 1),
    ],
)
def test_latest_version_ignores_unusable_releases(monkeypatch, payload):
    monkeypatch.setattr(releases, "urlopen", lambda request, timeout: FakeResponse(payload))

    assert releases.latest_version() is None


def test_latest_version_survives_an_offline_installation(monkeypatch):
    def offline(request, timeout):
        raise OSError("network unreachable")

    monkeypatch.setattr(releases, "urlopen", offline)

    assert releases.latest_version() is None


def test_release_status_returns_json(client, monkeypatch):
    monkeypatch.setattr("strong_data.views.update_available", lambda: True)

    response = client.get(reverse("release_status"))

    assert response.status_code == 200
    assert response.json() == {"update_available": True}
    assert "no-store" in response.headers["Cache-Control"]


def test_release_status_rejects_post(client):
    response = client.post(reverse("release_status"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_footer_links_the_version_and_the_repository(client):
    response = client.get(reverse("login"))
    body = response.content.decode()

    assert releases.RELEASES_URL in body
    assert releases.REPOSITORY_URL in body
    assert "GitHub" in body
    assert "Update available" in body
