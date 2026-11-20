# Development

Local setup and checks for working on the application.

## Setup

Python 3.14 is pinned in `.python-version`; uv installs it automatically.

```sh
uv sync --frozen
uv run python manage.py migrate
```

Settings are read from the environment: `STRONG_SECRET_KEY`, `STRONG_DEBUG`,
`STRONG_ALLOWED_HOSTS`, `STRONG_DB_PATH` and `STRONG_TIME_ZONE`. See
`.env.example`; never commit a real `.env`. With `STRONG_DEBUG` unset the app runs
in production mode and refuses to start without a real secret key, so either
export one or set `STRONG_DEBUG=true` for the local fallback. `STRONG_TIME_ZONE`
sets the zone the export's wall-clock timestamps are read in and the zone the UI
and API render. The test suite supplies its own synthetic key through
`tests/settings.py`, so `uv run pytest -q` needs no environment.

## Commands

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_no_private_data.py
```

CI runs these in the Linux development container, plus the lockfile check, the
dependency and image audits and the production-image check. To reproduce CI's
environment locally:

```sh
docker compose -f compose.development.yaml build web
docker compose -f compose.development.yaml run --rm web pytest -q
docker compose -f compose.development.yaml down
```

## Container development

`compose.development.yaml` is a standalone development stack. It builds the
`development` image target, serves on `127.0.0.1:8000` only, needs no `.env`, and
keeps all state — database, virtualenv, caches — on named volumes while your
working copy is bind-mounted into the container:

```sh
docker compose -f compose.development.yaml up --build
```

Rebuild after a dependency change so the seeded virtualenv is refreshed from the
image.

## Optional parity check

Set `STRONG_LOCAL_CSV` to a local export to run the opt-in parser parity test. It
is skipped when unset, so CI stays deterministic and never needs private data.
