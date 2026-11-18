# Contributing

## Setup

```sh
uv sync --frozen
```

Python 3.14 is pinned in `.python-version`; uv installs it automatically.

## Before opening a pull request

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_no_private_data.py
```

The same checks run in CI on a Linux runner. Docker-based commands are in
`AGENTS.md`.

## Rules

- Work in the phase order described under `Roadmap and status` in `README.md`; discuss
  larger changes in an issue first.
- Use Django migrations for all schema changes.
- Keep all fixtures and examples synthetic; never commit personal data, CSV files,
  databases, backups, secrets or `.env` files.
- Keep code free of comments unless a change explicitly requires them.

## License

Contributions are licensed under the PolyForm Noncommercial License 1.0.0 (see
`LICENSE` and `NOTICE`).
