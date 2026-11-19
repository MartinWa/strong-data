"""Django settings for the strong-data project."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("STRONG_DEBUG", "false").strip().lower() in {"1", "true", "yes"}

DEVELOPMENT_SECRET_KEY = "django-insecure-local-development-only"
PLACEHOLDER_SECRET_KEYS = frozenset({DEVELOPMENT_SECRET_KEY, "replace-with-a-long-random-value"})


def secret_key(debug: bool) -> str:
    value = os.environ.get("STRONG_SECRET_KEY", "").strip()
    if value and value not in PLACEHOLDER_SECRET_KEYS:
        return value
    if debug:
        return DEVELOPMENT_SECRET_KEY
    raise ImproperlyConfigured(
        "STRONG_SECRET_KEY must be set to a unique random value when STRONG_DEBUG is false."
    )


SECRET_KEY = secret_key(DEBUG)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("STRONG_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("STRONG_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
    "api.middleware.ApiResponseMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(os.environ.get("STRONG_STATIC_ROOT") or BASE_DIR / "staticfiles")
STATIC_ROOT.mkdir(exist_ok=True)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "sessions"

UPDATE_CHECK_ENABLED = os.environ.get("STRONG_UPDATE_CHECK", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
