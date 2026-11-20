# Development

Local setup and commands for working on the Django application.

## Setup

Python 3.14 is pinned in `.python-version`; uv installs it automatically.

```sh
uv sync --frozen
uv run python manage.py migrate
```

Configuration is read from the environment: `STRONG_SECRET_KEY`, `STRONG_DEBUG`,
`STRONG_ALLOWED_HOSTS`, `STRONG_DB_PATH` and `STRONG_TIME_ZONE`. See `.env.example`;
never commit a real `.env`.

`STRONG_TIME_ZONE` sets the zone Strong exports' wall-clock timestamps are read in,
and the zone the UI and API render. It defaults to `UTC`; the development container
keeps it there so tests and screenshots are stable.

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

Restart the container after adding a new template tag library:

```sh
docker compose -f compose.development.yaml restart web
```

Django caches the set of installed tag libraries per process, so a long-running
`runserver` can still answer `/sessions/` with `'formatting' is not a registered tag
library` after `workouts/templatetags/formatting.py` exists on disk. The bind mount is
fine; only the process is stale. Any page that reports a missing library lists `assets`
but not the new one — that is the signal to restart rather than to debug the module.

## Releases

A Git tag supplies the image version and the footer version through the
`STRONG_VERSION` build argument, so no version bump in `pyproject.toml` or `uv.lock`
is needed. Pushing a stable `X.Y.Z` tag on `main` triggers `.github/workflows/release.yml`,
which requires a successful CI run for the tagged commit, checks and audits both the
`linux/amd64` and `linux/arm64` images, publishes the tested index with per-platform
SBOM and provenance attestations, and creates the GitHub Release. Existing versions
are never overwritten and `latest` advances only for the current stable release.

On a clean, committed `main` checkout, create a local annotated tag in PowerShell:

```powershell
./tools/tag_release.ps1 -Version 1.0.0 -WhatIf
./tools/tag_release.ps1 -Version 1.0.0
```

Use the version you intend; `1.0.0` is illustrative. After the first stable tag,
omitting `-Version` increments its patch component. The helper pushes only when
explicitly given `-Push`, and never moves or deletes an existing tag. Confirm the
version before pushing: `git push --no-follow-tags origin refs/tags/<version>`.

The workflow ends by requiring the GHCR package to be pullable without
authentication, because GitHub creates container packages private even for a public
repository. It sets the visibility itself when the token allows it, which needs a
repository secret `PACKAGE_TOKEN` holding a token with `write:packages`. Without that
secret the first release finishes with the package private and the step fails with
the one-time instruction: open the package settings on the repository page and set
the visibility to public. Later releases inherit it.

## Optional parity check

Set `STRONG_LOCAL_CSV` to a local export to run the opt-in parser parity test. It is
skipped when unset, so CI stays deterministic and never needs private data.
