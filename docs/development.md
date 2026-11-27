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
sets the import zone for new sessions and the zone used to render local times.
Existing sessions keep their import zone for later merges. The test suite
supplies its own synthetic key through
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

## Reports benchmark

The reports page renders the same query layer as the API (`api/queries.py`), so a
new number belongs there and is covered by the parity suite. The benchmark tool
builds a synthetic dataset and times each block and the full page:

```sh
uv run python tools/benchmark_reports.py
uv run python tools/benchmark_reports.py --json
```

It uses a temporary SQLite database, needs no private data, and enforces the
reference budget (2.5 s for the full page, 1.0 s for any single block) unless
`--budget 0 --block-budget 0` is passed. CI runs the small-fixture correctness and
query-count checks and does not run the benchmark.

Reference dataset: 2,000 sessions, 60,000 sets and ten years on the Linux
development image. The pre-optimization baseline for the `all` volume series plus
the muscle breakdown alone was 5.0–5.1 s. After the shared query-layer pass the
recorded timings are:

| Step | Seconds |
| --- | --- |
| Series, volume, 12 weeks | 0.006 |
| Series, volume, 1 year | 0.014 |
| Series, volume, all time (chunked by year) | 0.145 |
| Muscle totals, all time | 0.233 |
| Consistency card, all time | 0.030 |
| Personal bests, all time | 0.179 |
| Yearly totals | 0.022 |
| Full page, 12 weeks | 0.577 |
| Full page, all time | 0.665 |

Re-run the tool after changing an aggregate; a block that regresses past 1.0 s, or
a page past 2.5 s, blocks release.

## Optional parity check

Set `STRONG_LOCAL_CSV` to a local export to run the opt-in parser parity test. It
is skipped when unset, so CI stays deterministic and never needs private data.
