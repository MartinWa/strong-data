# strong-data

Self-hosted Strong workout CSV import with a private SQLite database, a
server-rendered HTMX web UI, and a versioned, owner-scoped bearer-token JSON API.

## Stack

- Python 3.14, Django 5.2 LTS, django-ninja, uv, ruff
- SQLite only; server-rendered HTMX templates
- Non-root container, no published ports (traffic arrives via a TLS reverse proxy)

## Documentation

- `docs/usage.md` — using the app (planned)
- `docs/development.md` — local development (planned)
- `docs/deployment.md` — reverse-proxy deployment (planned)
- `docs/backup-and-recovery.md` — backing up SQLite (planned)
- `docs/data-model.md` — tables and derived fields (planned)
- `docs/api.md` — endpoint-by-endpoint API contract (planned)
- `SECURITY.md` — security policy and vulnerability reporting
- `CONTRIBUTING.md` — contribution workflow
- `LICENSE` / `NOTICE` — PolyForm Noncommercial 1.0.0

## Roadmap and status

Work is delivered in phases, in order:

- **P0 — Scaffold and hygiene** (current): repository layout, pinned tooling, CI,
  ignore rules and the private-data guard. No application behavior yet.
- **P1 — Parse and store**: CSV parsing, models and migrations, and the import flow.
- **P2 — API**: the versioned, owner-scoped JSON API and its published contract.
- **P3 — Package and operate**: container, compose files and deployment/backup docs.
- **P4 — Verification**: end-to-end checks on synthetic data and a PII scan.

Target the current phase and discuss larger changes in an issue first. The detailed
working plan is private; this summary and the linked docs are the public source of truth.

## License

PolyForm Noncommercial 1.0.0. See `LICENSE` and `NOTICE`.
