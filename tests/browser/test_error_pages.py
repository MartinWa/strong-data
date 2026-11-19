import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


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
