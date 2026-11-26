import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse


def read_static(path):
    return Path(finders.find(path)).read_text(encoding="utf-8")


def declarations(css, selector):
    opening = css.index("{", css.index(selector))
    depth = 0
    for index in range(opening, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                body = css[opening + 1 : index]
                return {
                    name: " ".join(value.split())
                    for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
                }
    raise AssertionError(f"unbalanced block for {selector}")


def test_the_dark_palette_is_identical_for_the_os_and_the_pinned_choice():
    css = read_static("workouts/app.css")

    from_os = declarations(css, ':root:not([data-theme="light"])')
    from_choice = declarations(css, ':root[data-theme="dark"] {')

    assert from_os == from_choice
    assert from_os["--bg"] == "#12151a"
    assert from_os["--text"] == "#e7ebf0"


def test_a_pinned_light_choice_beats_a_dark_os():
    css = read_static("workouts/app.css")

    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root:not([data-theme="light"])' in css
    assert re.search(r":root\s*\{\s*color-scheme: light;", css)
    assert re.search(r":root\[data-theme=\"dark\"\]\s*\{\s*color-scheme: dark;", css)


def test_the_theme_is_resolved_before_the_stylesheet_is_requested(client):
    content = client.get(reverse("login")).content.decode()

    assert content.index("localStorage.getItem(key)") < content.index("workouts/app.css")
    assert '"strong-data:theme"' in content
    assert "matchMedia" in content


def test_pages_send_a_csp_header_with_a_per_request_nonce(client):
    first = client.get(reverse("login"))
    second = client.get(reverse("login"))

    policy = first.headers["Content-Security-Policy"]
    for directive in (
        "default-src 'self'",
        "script-src 'self' 'nonce-",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ):
        assert directive in policy

    first_nonce = re.search(r'<script nonce="([^"]+)">', first.content.decode()).group(1)
    second_nonce = re.search(r'<script nonce="([^"]+)">', second.content.decode()).group(1)

    assert first_nonce != second_nonce
    assert f"'nonce-{first_nonce}'" in policy
    assert f"'nonce-{second_nonce}'" in second.headers["Content-Security-Policy"]


def test_the_toggle_is_hidden_until_javascript_can_drive_it(client):
    content = client.get(reverse("login")).content.decode()

    assert re.search(
        r'<button class="theme-toggle" type="button" data-theme-toggle '
        r'aria-pressed="false" hidden>',
        content,
    )
    assert ">Dark theme</span>" in content
    assert 'src="/static/workouts/theme.js"' in content


@pytest.mark.django_db
def test_the_toggle_is_offered_on_signed_in_pages_too(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert "data-theme-toggle" in content


def test_the_toggle_remembers_the_choice_in_local_storage():
    script = read_static("workouts/theme.js")

    assert 'const KEY = "strong-data:theme";' in script
    assert "window.localStorage.getItem(KEY)" in script
    assert "window.localStorage.setItem(KEY, value)" in script
    assert "sessionStorage" not in script


def test_the_toggle_follows_the_os_until_a_choice_is_pinned():
    script = read_static("workouts/theme.js")

    assert 'matchMedia("(prefers-color-scheme: dark)")' in script
    assert "if (pinned()) return;" in script


def test_each_theme_has_its_own_icon_and_only_one_is_shown():
    css = read_static("workouts/app.css")

    assert ".theme-icon-moon {\n  display: none;\n}" in css
    assert ':root[data-theme="dark"] .theme-icon-sun {\n  display: none;\n}' in css
    assert ':root[data-theme="dark"] .theme-icon-moon {\n  display: block;\n}' in css
