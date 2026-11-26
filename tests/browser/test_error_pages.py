from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import Client
from django.urls import reverse

from strong_data.version import app_version
from strong_data.views import server_error


@pytest.mark.django_db
def test_unknown_address_renders_the_branded_404(client, settings):
    settings.DEBUG = False

    response = client.get("/definitely/not/a/page/")

    assert response.status_code == 404
    assert "404.html" in [template.name for template in response.templates]
    content = response.content.decode()
    assert "Page not found" in content
    assert 'href="/accounts/login/"' in content
    assert "Go to sessions" not in content


@pytest.mark.django_db
def test_404_offers_a_way_back_for_a_logged_in_user(client, settings):
    settings.DEBUG = False
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get("/definitely/not/a/page/").content.decode()

    assert "Go to sessions" in content
    assert f'href="{reverse("sessions")}"' in content


@pytest.mark.django_db(transaction=True)
def test_unhandled_exception_renders_the_branded_500(settings):
    settings.DEBUG = False
    settings.ROOT_URLCONF = "tests.browser.boom_urls"

    response = Client(raise_request_exception=False).get("/boom/")

    assert response.status_code == 500
    assert "500.html" in [template.name for template in response.templates]
    content = response.content.decode()
    assert "Something went wrong" in content
    assert "Your data is unchanged" not in content


@pytest.mark.django_db
def test_api_is_reachable_from_the_footer_but_not_the_nav(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert 'class="site-nav"' in content
    nav = content.split('class="site-nav"')[1].split("</nav>")[0]
    assert "/api/v1/docs" not in nav
    assert "API reference" in content


def test_500_handler_does_not_evaluate_authentication(rf):
    with mock.patch(
        "django.contrib.auth.context_processors.auth",
        side_effect=OperationalError("session store unavailable"),
    ):
        response = server_error(rf.get("/boom/"))

    assert response.status_code == 500
    assert b"Something went wrong" in response.content
    assert b"GitHub" in response.content
    assert app_version().encode() not in response.content


def test_500_does_not_claim_that_nothing_was_written(rf):
    content = server_error(rf.get("/boom/")).content.decode()

    assert "Your data is unchanged" not in content


@pytest.mark.django_db
def test_500_renders_its_branding_without_a_request_context(rf):
    content = server_error(rf.get("/boom/")).content.decode()

    assert "strong-data" in content
    assert "GitHub" in content
