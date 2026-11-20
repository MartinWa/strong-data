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

## Contributor agreement

Before your first pull request can be merged, sign the [Contributor License
Agreement](CLA.md). An app comments on your pull request with a signing link; click
it once and the signature covers your future contributions too. You keep the
copyright in your contribution.

Signing matters because the project is dual licensed: it is published under the
PolyForm Noncommercial License 1.0.0 and also offered commercially. The agreement is
what lets a contribution be part of both. If you contribute in the course of
employment, read section 6 of the agreement first: your employer may own the work, and
an authorised person has to sign for the entity.

The project does not use a Developer Certificate of Origin (`Signed-off-by`), because
a DCO certifies that a contribution may be distributed under the project's current
licence and does not permit relicensing it.

### For maintainers

Signatures are collected by [CLA Assistant](https://cla-assistant.io), a free GitHub
app, not by a workflow in this repository:

1. Create a public gist containing `CLA.md` and copy its URL.
2. Sign in at <https://cla-assistant.io> with GitHub, add this repository, and paste
the gist URL.
3. Make **CLA Assistant** a required status check in the branch protection rules for
   `main`.

Signatures are stored in that gist, so contributor accounts never enter this
repository. An earlier draft used the `contributor-assistant/github-action` action;
it was archived upstream in 2026 and has no maintained release, so it is not used.

## License

Contributions are licensed under the PolyForm Noncommercial License 1.0.0 (see
`LICENSE` and `NOTICE`), and under the terms of the Contributor License Agreement.
