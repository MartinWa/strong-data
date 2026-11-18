#!/bin/sh
set -eu

uv run python manage.py migrate --noinput
exec uv run python -m tools.serve
