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

## Commands

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_no_private_data.py
```

The same checks run in CI on a Linux runner. Docker-based commands are in `AGENTS.md`.

## Optional parity check

Set `STRONG_LOCAL_CSV` to a local export to run the opt-in parser parity test. It is
skipped when unset, so CI stays deterministic and never needs private data.
