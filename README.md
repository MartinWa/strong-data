# strong-data

Self-hosted Strong workout CSV import with a private SQLite database, a
server-rendered web UI, and a versioned, owner-scoped bearer-token JSON API.

## Stack

- Python 3.14, Django 5.2 LTS, django-ninja, uv, ruff
- SQLite only; server-rendered Django templates, no CDN and no SPA
- Non-root container, no published ports (traffic arrives via a TLS reverse proxy)

## Run with Docker

The image runs as a non-root user and publishes no ports; put it behind your own
TLS reverse proxy on a private Docker network. Compose builds it, applies
migrations and serves the app with waitress, with SQLite on a named volume.
Release tags publish a tested, attested image to GHCR.

```sh
cp .env.example .env
docker compose up -d --build
```

For a local dev server with no `.env` required:

```sh
docker compose -f compose.development.yaml up --build
```

## Documentation

- `docs/usage.md` — using the app
- `docs/development.md` — local development
- `docs/deployment.md` — reverse-proxy deployment and Compose
- `docs/backup-and-recovery.md` — backing up and restoring SQLite
- `docs/data-model.md` — tables and derived fields
- `docs/api.md` — endpoint-by-endpoint API contract and generated OpenAPI reference
- `SECURITY.md` — security policy and vulnerability reporting
- `CONTRIBUTING.md` — contribution workflow
- `LICENSE` / `NOTICE` — PolyForm Noncommercial 1.0.0

## Roadmap and status

Work is delivered in phases, in order:

- **P0 — Scaffold and hygiene**: repository layout, pinned tooling, CI, ignore rules
  and the private-data guard.
- **P1 — Parse and store**: CSV parsing, models and migrations, and the import flow.
- **P2 — API**: the versioned, owner-scoped JSON API and its published contract.
- **P3 — Package and operate** (complete): container with dev-only tooling excluded from
  the production image, compose files, deployment and backup docs, version/footer links,
  API reference, hardened CI (lockfile, dependency and image auditing) and an attested
  tag-based release pipeline to GHCR.
- **P4 — Verification** (complete): end-to-end checks on synthetic data, a PII and
  secret scan, and confirmation that every documented command passes without the
  private reference export.

Target the current phase and discuss larger changes in an issue first. The detailed
working plan is private; this summary and the linked docs are the public source of truth.

## License

PolyForm Noncommercial 1.0.0. See `LICENSE` and `NOTICE`.
