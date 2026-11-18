# Security Policy

## Personal data

Workout records are personal health data. This repository is public and must
contain **no** personal data of any kind:

- no real Strong CSV exports, sessions, weights, reps, dates or notes
- no real names, accounts, e-mail addresses, tokens or token hashes
- no real hostnames, volume paths, usernames, groups or UIDs
- no real database or backup files

`planning/` and `reference/` are private, gitignored and never committed. Fixtures,
screenshots, examples and documentation use wholly synthetic data; redacting real
data is not sufficient. Committed tests never read a real export. An optional local
parity check may point at one via `STRONG_LOCAL_CSV` and is skipped when unset.

A CI guard fails if any CSV, database, backup or private-path file is tracked:

```sh
uv run python tools/check_no_private_data.py
```

## Reporting a vulnerability

Use GitHub's private vulnerability reporting ("Report a vulnerability" on the
repository's Security tab). Do not open a public issue for a security problem.
Include the affected version, the impact and a minimal reproduction. You should
receive an acknowledgement; fixes are coordinated privately before disclosure.

## Deployment

The application is intended for self-hosting behind a TLS reverse proxy. It
publishes no ports. Protect the proxy, keep the SQLite database and backups
private, and revoke API tokens that are no longer needed.
