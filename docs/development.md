# Development

Local setup and commands for working on the Django application.

## Setup

Python 3.14 is pinned in `.python-version`; uv installs it automatically.

```sh
uv sync --frozen
uv run python manage.py migrate
```

Configuration is read from the environment: `STRONG_SECRET_KEY`, `STRONG_DEBUG`,
`STRONG_ALLOWED_HOSTS` and `STRONG_DB_PATH`. See `.env.example`; never commit a real
`.env`.

With `STRONG_DEBUG` unset the app runs in production mode and refuses to start
without a real `STRONG_SECRET_KEY`. For local commands either export a key or set
`STRONG_DEBUG=true` to use the development fallback. The test suite supplies its own
synthetic key through `tests/settings.py`, so `uv run pytest -q` needs no
environment.

## Commands

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_no_private_data.py
```

The same checks run in CI inside the development container. Docker-based commands are
in `AGENTS.md`.

## Container development

The standalone development stack builds the `development` image target, serves on
`127.0.0.1:8000`, requires no `.env`, and bind-mounts your working copy:

```sh
docker compose -f compose.development.yaml up --build
```

Database, virtualenv and caches live on named volumes; rebuild after dependency
changes so the seeded virtualenv is refreshed from the image.

## Optional parity check

Set `STRONG_LOCAL_CSV` to a local export to run the opt-in parser parity test. It is
skipped when unset, so CI stays deterministic and never needs private data.
