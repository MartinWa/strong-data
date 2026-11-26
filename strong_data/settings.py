"""Django settings for the strong-data project."""

import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("STRONG_DEBUG", "false").strip().lower() in {"1", "true", "yes"}

DEVELOPMENT_SECRET_KEY = "django-insecure-local-development-only"
PLACEHOLDER_SECRET_KEYS = frozenset({DEVELOPMENT_SECRET_KEY, "replace-with-a-long-random-value"})


def read_setting(name: str) -> str:
    """Read a setting, accepting a file path through the conventional NAME_FILE form."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    path = os.environ.get(f"{name}_FILE", "").strip()
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return ""


def secret_key(debug: bool) -> str:
    value = read_setting("STRONG_SECRET_KEY")
    if value and value not in PLACEHOLDER_SECRET_KEYS:
        return value
    if debug:
        return secrets.token_urlsafe(50)
    raise ImproperlyConfigured(
        "STRONG_SECRET_KEY must be set to a unique random value when STRONG_DEBUG is false."
    )


SECRET_KEY = secret_key(DEBUG)


def allowed_hosts(debug: bool) -> list[str]:
    hosts = [
        host.strip()
        for host in os.environ.get("STRONG_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
        if host.strip()
    ]
    if not debug and "*" in hosts:
        raise ImproperlyConfigured(
            "STRONG_ALLOWED_HOSTS must list explicit hostnames when STRONG_DEBUG is false; "
            "'*' would accept any Host header."
        )
    return hosts


ALLOWED_HOSTS = allowed_hosts(DEBUG)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("STRONG_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


def proxy_ssl_header(trusted_proxy: str) -> tuple[str, str] | None:
    value = trusted_proxy.strip()
    if value and value != "*":
        return ("HTTP_X_FORWARDED_PROTO", "https")
    return None


SECURE_PROXY_SSL_HEADER = proxy_ssl_header(os.environ.get("STRONG_TRUSTED_PROXY", ""))
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ninja",
    "workouts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "strong_data.middleware.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "api.middleware.ApiResponseMiddleware",
]

ROOT_URLCONF = "strong_data.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "strong_data.context_processors.app_info",
            ],
        },
    },
]

WSGI_APPLICATION = "strong_data.wsgi.application"
ASGI_APPLICATION = "strong_data.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("STRONG_DB_PATH") or BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"


def default_time_zone() -> str:
    name = read_setting("STRONG_TIME_ZONE") or "UTC"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"STRONG_TIME_ZONE must be an IANA zone name such as Europe/Stockholm, not {name!r}."
        ) from exc
    return name


TIME_ZONE = default_time_zone()
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(os.environ.get("STRONG_STATIC_ROOT") or BASE_DIR / "staticfiles")
STATIC_ROOT.mkdir(exist_ok=True)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "sessions"

DATA_UPLOAD_MAX_NUMBER_FIELDS = 8000

UPDATE_CHECK_ENABLED = os.environ.get("STRONG_UPDATE_CHECK", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}


DEFAULT_PENDING_SWEEP_SECONDS = 900


def sweep_interval(raw: str) -> int:
    value = raw.strip()
    if not value:
        return DEFAULT_PENDING_SWEEP_SECONDS
    try:
        seconds = int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(
            "STRONG_PENDING_SWEEP_SECONDS must be a whole number of seconds, or 0 to disable."
        ) from exc
    if seconds < 0:
        raise ImproperlyConfigured(
            "STRONG_PENDING_SWEEP_SECONDS must be a whole number of seconds, or 0 to disable."
        )
    return seconds


PENDING_SWEEP_SECONDS = sweep_interval(os.environ.get("STRONG_PENDING_SWEEP_SECONDS", ""))
