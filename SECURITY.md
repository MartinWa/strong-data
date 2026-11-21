# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub advisory reporting:

<https://github.com/MartinWa/strong-data/security/advisories/new>

Do not open a public issue for a security problem. Include the affected version,
the impact and a minimal reproduction. Reports are acknowledged within 7 days;
fixes are coordinated privately and the advisory is published after disclosure.

## Personal data

Workout records are personal health data and this repository is public, so it must
contain none of it:

- no real Strong exports, sessions, weights, reps, dates or notes
- no real names, accounts, e-mail addresses, tokens or token hashes
- no real hostnames, volume paths, usernames, groups or UIDs
- no database or backup files

Fixtures, screenshots, examples and documentation are wholly synthetic; redacting
real data is not sufficient. An optional local parity check may read a real export
via `STRONG_LOCAL_CSV` and is skipped when unset; committed tests never do. CI
fails if a CSV, database, backup or private-path file is tracked
(`uv run python tools/check_no_private_data.py`).

## Self-hosting

Run the app behind a TLS reverse proxy; it publishes no ports. Keep the SQLite
database and backups private, and revoke API tokens you no longer need. See
[deployment](docs/deployment.md) and [backup and recovery](docs/backup-and-recovery.md).
