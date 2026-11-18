#!/bin/sh
set -eu

uv run python manage.py migrate --noinput
exec uv run waitress-serve --listen="0.0.0.0:${STRONG_PORT:-8000}" strong_data.wsgi:application
