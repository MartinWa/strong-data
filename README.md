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

## License

PolyForm Noncommercial 1.0.0. See `LICENSE` and `NOTICE`.
