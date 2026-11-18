# Backup and recovery

The SQLite database is the whole application state: accounts, sessions, sets,
muscle corrections and token metadata. The file is `/app/data/strong.sqlite3`
inside the container, on the Compose volume mounted at `/app/data` (usually
`strong-data_data`).

**Backups are personal health data.** Treat them like the live database: encrypt
them, store them off-host with restricted access, never attach them to an issue
or commit, and delete local copies when you are done. The repository's hygiene
guard rejects tracked `*.sqlite3`, `*.db`, `*.dump` and similar files.

## Back up while running

Use SQLite's online backup API so a consistent copy is taken without stopping the
app. Create the copy on the data volume, move it to the host, then remove it:

```sh
docker compose exec -T web uv run python -c "import sqlite3; s = sqlite3.connect('/app/data/strong.sqlite3'); d = sqlite3.connect('/app/data/backup.sqlite3'); s.backup(d); d.close(); s.close()"
docker compose cp web:/app/data/backup.sqlite3 ./backup.sqlite3
docker compose exec -T web rm -f /app/data/backup.sqlite3
```

Move `backup.sqlite3` to encrypted storage and record the date. A plain file copy
of the database is not a consistent backup while the app is writing; prefer the
command above. Do not rely on the container filesystem surviving a rebuild.

## Verify a backup

Check integrity before you need it:

```sh
uv run python -c "import sqlite3; c = sqlite3.connect('backup.sqlite3'); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()"
```

The result should be `ok`. Optionally restore into a separate installation and
confirm sessions and exercises are present.

## Restore

Restoring replaces the live database. Take a current backup first, then stop
writes, install the backup, fix its ownership and restart:

```sh
docker compose up -d
docker compose cp ./backup.sqlite3 web:/app/data/strong.sqlite3
docker compose exec -T web chown app:app /app/data/strong.sqlite3
docker compose restart web
```

The startup script applies migrations to the restored database automatically.
Confirm the restore succeeded:

```sh
docker compose exec -T web uv run python manage.py check
curl -fsS http://127.0.0.1:8000/api/v1/healthz
```

Then log in and verify your sessions, muscle-group corrections and tokens. If
anything is wrong, stop the app and restore the previous backup the same way.

## Schedule and retain

Run backups on a schedule that matches how often you import, keep several dated
copies, and periodically exercise a clean restore. Tokens are scoped to the
database, so a restored database also restores token validity; revoke any token
you no longer trust after a restore.
