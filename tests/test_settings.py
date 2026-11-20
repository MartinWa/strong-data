import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from strong_data.settings import (
    DEFAULT_PENDING_SWEEP_SECONDS,
    DEVELOPMENT_SECRET_KEY,
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

    assert secret_key(debug=True) == DEVELOPMENT_SECRET_KEY


def test_development_ignores_the_placeholder(monkeypatch):
    monkeypatch.setenv("STRONG_SECRET_KEY", PLACEHOLDER)

    assert secret_key(debug=True) == DEVELOPMENT_SECRET_KEY


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
