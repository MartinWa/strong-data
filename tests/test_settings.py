import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from strong_data.settings import (
    DEFAULT_PENDING_SWEEP_SECONDS,
    DEVELOPMENT_SECRET_KEY,
    PLACEHOLDER_SECRET_KEYS,
    allowed_hosts,
    default_time_zone,
    proxy_ssl_header,
    secret_key,
    sweep_interval,
)

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "replace-with-a-long-random-value"
REAL_SECRET = "synthetic-test-secret-key-never-for-runtime-000000000000"


def test_production_requires_an_explicit_secret(monkeypatch):
    monkeypatch.delenv("STRONG_SECRET_KEY", raising=False)

    with pytest.raises(ImproperlyConfigured):
        secret_key(debug=False)


def test_production_rejects_the_example_placeholder(monkeypatch):
    monkeypatch.setenv("STRONG_SECRET_KEY", PLACEHOLDER)

    with pytest.raises(ImproperlyConfigured):
        secret_key(debug=False)


def test_production_rejects_the_development_fallback(monkeypatch):
    monkeypatch.setenv("STRONG_SECRET_KEY", DEVELOPMENT_SECRET_KEY)

    with pytest.raises(ImproperlyConfigured):
        secret_key(debug=False)


def test_production_accepts_a_real_secret(monkeypatch):
    monkeypatch.setenv("STRONG_SECRET_KEY", REAL_SECRET)

    assert secret_key(debug=False) == REAL_SECRET


def test_development_falls_back_without_a_secret(monkeypatch):
    monkeypatch.delenv("STRONG_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRONG_SECRET_KEY_FILE", raising=False)

    first = secret_key(debug=True)
    second = secret_key(debug=True)

    assert first not in PLACEHOLDER_SECRET_KEYS
    assert len(first) >= 40
    assert first != second


def test_development_ignores_the_placeholder(monkeypatch):
    monkeypatch.setenv("STRONG_SECRET_KEY", PLACEHOLDER)

    first = secret_key(debug=True)
    second = secret_key(debug=True)

    assert first not in PLACEHOLDER_SECRET_KEYS
    assert len(first) >= 40
    assert first != second


def test_production_reads_the_secret_from_a_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text(REAL_SECRET + "\n", encoding="utf-8")
    monkeypatch.delenv("STRONG_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRONG_SECRET_KEY_FILE", str(secret_file))

    assert secret_key(debug=False) == REAL_SECRET


def test_environment_secret_wins_over_the_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-secret-used-in-the-wrong-place-000000000", encoding="utf-8")
    monkeypatch.setenv("STRONG_SECRET_KEY", REAL_SECRET)
    monkeypatch.setenv("STRONG_SECRET_KEY_FILE", str(secret_file))

    assert secret_key(debug=False) == REAL_SECRET


def secure_cookies(**overrides):
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"STRONG_DEBUG", "STRONG_SECRET_KEY"}
    }
    env.update(overrides)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import strong_data.settings as s;"
            " print(s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE)",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def test_secure_cookies_are_on_in_production():
    assert secure_cookies(STRONG_SECRET_KEY=REAL_SECRET) == "True True"


def test_secure_cookies_are_off_in_development():
    assert secure_cookies(STRONG_DEBUG="true") == "False False"


def run_settings(code, **overrides):
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "STRONG_DEBUG",
            "STRONG_SECRET_KEY",
            "STRONG_SECRET_KEY_FILE",
            "STRONG_ALLOWED_HOSTS",
            "STRONG_TRUSTED_PROXY",
        }
    }
    env.update(overrides)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )


def test_production_rejects_a_wildcard_allowed_hosts():
    result = run_settings(
        "import strong_data.settings",
        STRONG_SECRET_KEY=REAL_SECRET,
        STRONG_ALLOWED_HOSTS="*",
    )

    assert result.returncode != 0
    assert "STRONG_ALLOWED_HOSTS" in result.stderr


def test_debug_allows_a_wildcard_allowed_hosts():
    result = run_settings(
        "import strong_data.settings as s; print(s.ALLOWED_HOSTS)",
        STRONG_DEBUG="true",
        STRONG_ALLOWED_HOSTS="*",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['*']"


def test_production_accepts_explicit_allowed_hosts():
    result = run_settings(
        "import strong_data.settings as s; print(s.ALLOWED_HOSTS)",
        STRONG_SECRET_KEY=REAL_SECRET,
        STRONG_ALLOWED_HOSTS="workouts.example.com, www.workouts.example.com,",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['workouts.example.com', 'www.workouts.example.com']"


def test_allowed_hosts_drops_empty_entries(monkeypatch):
    monkeypatch.setenv("STRONG_ALLOWED_HOSTS", " a.example.com ,,b.example.com,")

    assert allowed_hosts(debug=False) == ["a.example.com", "b.example.com"]


def test_allowed_hosts_rejects_a_wildcard_in_production(monkeypatch):
    monkeypatch.setenv("STRONG_ALLOWED_HOSTS", "a.example.com, *")

    with pytest.raises(ImproperlyConfigured):
        allowed_hosts(debug=False)


def test_allowed_hosts_accepts_a_wildcard_in_debug(monkeypatch):
    monkeypatch.setenv("STRONG_ALLOWED_HOSTS", "*")

    assert allowed_hosts(debug=True) == ["*"]


@pytest.mark.parametrize("value", ["", "   ", "*"])
def test_proxy_ssl_header_is_off_without_a_specific_proxy(value):
    assert proxy_ssl_header(value) is None


def test_proxy_ssl_header_honors_forwarded_proto_for_a_specific_proxy():
    assert proxy_ssl_header("10.0.0.9") == ("HTTP_X_FORWARDED_PROTO", "https")
    assert proxy_ssl_header(" proxy.internal ") == ("HTTP_X_FORWARDED_PROTO", "https")


def test_module_enables_the_proxy_ssl_header_only_for_a_specific_proxy():
    specific = run_settings(
        "import strong_data.settings as s; print(s.SECURE_PROXY_SSL_HEADER)",
        STRONG_SECRET_KEY=REAL_SECRET,
        STRONG_TRUSTED_PROXY="10.0.0.9",
    )
    wildcard = run_settings(
        "import strong_data.settings as s; print(s.SECURE_PROXY_SSL_HEADER)",
        STRONG_SECRET_KEY=REAL_SECRET,
        STRONG_TRUSTED_PROXY="*",
    )

    assert specific.returncode == 0, specific.stderr
    assert specific.stdout.strip() == "('HTTP_X_FORWARDED_PROTO', 'https')"
    assert wildcard.returncode == 0, wildcard.stderr
    assert wildcard.stdout.strip() == "None"


def test_time_zone_defaults_to_utc(monkeypatch):
    monkeypatch.delenv("STRONG_TIME_ZONE", raising=False)

    assert default_time_zone() == "UTC"


def test_time_zone_accepts_an_iana_name(monkeypatch):
    monkeypatch.setenv("STRONG_TIME_ZONE", "Europe/Stockholm")

    assert default_time_zone() == "Europe/Stockholm"


@pytest.mark.parametrize("value", ["Mars/Olympus", "UTC+2", "../etc/passwd", "/etc"])
def test_time_zone_rejects_anything_but_an_iana_name(monkeypatch, value):
    monkeypatch.setenv("STRONG_TIME_ZONE", value)

    with pytest.raises(ImproperlyConfigured):
        default_time_zone()


def test_sweep_interval_defaults_to_fifteen_minutes():
    assert sweep_interval("900") == 900


@pytest.mark.parametrize("value", ["", "   "])
def test_sweep_interval_falls_back_when_unset(value):
    assert sweep_interval(value) == DEFAULT_PENDING_SWEEP_SECONDS


def test_sweep_interval_accepts_zero_to_disable_the_sweep():
    assert sweep_interval("0") == 0


@pytest.mark.parametrize("value", ["soon", "15m", "-1"])
def test_sweep_interval_rejects_anything_but_seconds(value):
    with pytest.raises(ImproperlyConfigured):
        sweep_interval(value)


def test_settings_import_fails_without_a_secret_in_production():
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"STRONG_SECRET_KEY", "STRONG_DEBUG"}
    }

    result = subprocess.run(
        [sys.executable, "-c", "import strong_data.settings"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert b"STRONG_SECRET_KEY" in result.stderr
