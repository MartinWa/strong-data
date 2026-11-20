# strong-data

Self-hosted Strong workout CSV import with a private SQLite database, a
server-rendered web UI, and a versioned, owner-scoped bearer-token JSON API.

## Stack

- Python 3.14, Django 5.2 LTS, django-ninja, uv, ruff
- SQLite only; server-rendered Django templates, no CDN and no SPA
- Non-root container, no published ports by default (traffic arrives via a TLS
  reverse proxy), read-only root filesystem, all capabilities dropped
- Released images for `linux/amd64` and `linux/arm64`; no external database, no
  sidecar container, no CDN, no telemetry

## Run with Docker

Requires Docker Engine 24+ with a current Docker Compose release, and a TLS
reverse proxy.

```sh
docker pull ghcr.io/martinwa/strong-data:latest
# or build from this working copy instead:
#   docker build --target production -t strong-data:local .
#   and set STRONG_IMAGE=strong-data:local in .env

mkdir -p data && sudo chown -R 1000:1000 data
cp .env.example .env      # STRONG_SECRET_KEY and STRONG_ALLOWED_HOSTS; the example
                          # already sets STRONG_TRUSTED_PROXY=*
docker compose up -d
docker network connect strong-data caddy   # your proxy, forwarding to web:8000
```

The database lives in `./data` on the host, so backups are plain files. If your
proxy runs on the host instead of in a container, add the loopback port with
`-f compose.host-port.yaml`. To build from this working copy rather than pull a
release, add `-f compose.local-build.yaml`, which builds and tags `strong-data:local`. All
variables, both proxy patterns and the upgrade path are in `docs/deployment.md`.

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
- `docs/api.md` — API auth, envelope, guardrails and derived-number definitions
- `SECURITY.md` — security policy and vulnerability reporting
- `CONTRIBUTING.md` — contribution workflow
- `CLA.md` — contributor license agreement, signature required before a first merge
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

PolyForm Noncommercial 1.0.0 — source-available, not OSI open source. Anyone may
run, modify and share it for any noncommercial purpose, including a home lab, a
nonprofit or research use. Commercial use requires a separate license: open an
topic in this repository's Discussions to arrange one. See `LICENSE` and `NOTICE`.

Contributions are accepted under `CLA.md`, which keeps your copyright and grants
the project the rights that dual licensing needs.
