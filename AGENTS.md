# AGENTS.md

Instructions for automated agents working in this repository.

## Ground rules

- `README.md` and `docs/` are the source of truth for behavior. Keep them in sync
  with any change; the phased plan is retired.
- `planning/` and `reference/` are private and gitignored. Never commit their
  contents, and never read `reference/strong_workouts.csv` except through the
  opt-in `STRONG_LOCAL_CSV` parity check described in `docs/development.md`.
- Never commit CSV, database, backup, `.env`, token or other personal-data files.
  All examples and fixtures must be wholly synthetic.
- Use Django migrations, never hand-edited schemas.
- No comments in code unless explicitly requested.

## Commands

Run from the repository root. Python is pinned by `.python-version` (3.14). The
local check commands are listed in `docs/development.md`.

Container-based verification (matches CI's Linux environment). The development
stack builds the `development` target and runs every check inside it:

```sh
docker compose -f compose.development.yaml build web
docker compose -f compose.development.yaml run --rm web ruff check .
docker compose -f compose.development.yaml run --rm web ruff format --check .
docker compose -f compose.development.yaml run --rm web pytest -q
docker compose -f compose.development.yaml run --rm web python tools/check_no_private_data.py
docker compose -f compose.development.yaml down
```

Production image verification:

```sh
docker build --target production -t strong-data:prod .
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --tmpfs /tmp \
  --env STRONG_SECRET_KEY=synthetic-local-check-key-never-for-runtime-000000000 \
  --env STRONG_ALLOWED_HOSTS=127.0.0.1 \
  strong-data:prod python -m tools.check_production
```

## Layout

- `pyproject.toml`, `uv.lock`, `.python-version` — pinned toolchain
- `tools/` — repository scripts (hygiene guard, dev entrypoint, production check,
  image audit, release publisher)
- `tests/` — `parsing/`, `import/`, `api/`, `browser/`, `fixtures/`
- `docs/` — usage, deployment, backup/recovery, development, API
- `planning/` — private working notes (never committed)
- `.github/workflows/ci.yml` — lint, test and hygiene checks in the development
  container, plus dependency and production-image auditing
- `.github/workflows/release.yml` — tag-based image publishing with attestations

## Definition of done for a change

`uv run pytest -q`, `ruff check`, `ruff format --check` and the hygiene guard all
pass in the Linux development container, the production image passes
`tools/check_production.py`, with no private data present.
