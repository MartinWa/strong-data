import re

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.urls import reverse


def render_asset(path):
    template = Template("{% load assets %}{% asset '" + path + "' %}")
    return template.render(Context())


@pytest.mark.django_db
def test_asset_urls_are_plain_without_debug(settings):
    settings.DEBUG = False

    assert render_asset("workouts/app.css") == "/static/workouts/app.css"


@pytest.mark.django_db
def test_asset_urls_carry_mtime_in_debug(settings):
    settings.DEBUG = True

    url = render_asset("workouts/app.css")

    assert re.fullmatch(r"/static/workouts/app\.css\?v=\d+", url)


@pytest.mark.django_db
def test_asset_urls_change_when_the_file_changes(settings):
    settings.DEBUG = True

    first = render_asset("workouts/app.css")
    second = render_asset("workouts/releases.js")

    assert first != second


@pytest.mark.django_db
def test_missing_asset_falls_back_to_plain_url(settings):
    settings.DEBUG = True

    assert render_asset("workouts/absent.css") == "/static/workouts/absent.css"


@pytest.mark.django_db
def test_sessions_page_versions_its_assets_in_debug(client, settings):
    settings.DEBUG = True
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert re.search(r'href="/static/workouts/app\.css\?v=\d+"', content)
    assert re.search(r'src="/static/workouts/filters\.js\?v=\d+"', content)
    assert re.search(r'src="/static/workouts/releases\.js\?v=\d+"', content)
