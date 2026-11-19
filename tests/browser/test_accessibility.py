import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse


@pytest.mark.django_db
def test_pages_offer_a_skip_link_to_a_focusable_main(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert 'class="skip-link" href="#main"' in content
    assert '<main class="container" id="main" tabindex="-1">' in content


@pytest.mark.django_db
def test_brand_link_has_a_spoken_name(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert 'aria-label="strong-data"' in content


@pytest.mark.django_db
def test_pages_declare_a_favicon(client):
    content = client.get(reverse("login")).content.decode()

    assert 'rel="icon"' in content
    assert "favicon.svg" in content


def read_static(path):
    return Path(finders.find(path)).read_text(encoding="utf-8")


def test_favicon_matches_the_light_accent_colour():
    css = read_static("workouts/app.css")
    svg = read_static("workouts/favicon.svg")
    accent = re.search(r"--accent:\s*(#[0-9a-fA-F]{6})", css).group(1)

    assert accent in svg


@pytest.mark.django_db
def test_flash_messages_are_announced(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    response = client.post(reverse("tokens"), {"name": "reader"})

    assert response.status_code == 200
    assert 'class="messages" role="status" aria-live="polite"' in response.content.decode()
