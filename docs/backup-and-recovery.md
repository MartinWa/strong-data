# Backup and recovery

The SQLite database is the whole application state: accounts, sessions, sets,
muscle corrections and token metadata. It is `strong.sqlite3` in the `data`
directory next to `compose.yaml`, which the container mounts at `/app/data`.

**Backups are personal health data.** Treat them like the live database: encrypt
them, store them off-host with restricted access, never attach them to an issue
or commit, and delete local copies when you are done. The repository's hygiene
guard rejects tracked `*.sqlite3`, `*.db`, `*.dump` and similar files, and
`.gitignore` already excludes `data/`.

## Back up while running

Use SQLite's online backup API so a consistent copy is taken without stopping the
app. Because the database lives on a host directory, the copy appears on the host
directly:

```sh
docker compose exec -T web python -c "import sqlite3; s = sqlite3.connect('/app/data/strong.sqlite3'); d = sqlite3.connect('/app/data/backup.sqlite3'); s.backup(d); d.close(); s.close()"
mv data/backup.sqlite3 ./strong-data-$(date +%F).sqlite3
```

Do not copy `strong.sqlite3` directly while the app is running. In its default
write-ahead logging mode the newest committed data can live in
`strong.sqlite3-wal`, so a plain file copy of the database alone can be stale or
torn. If you must take a filesystem-level snapshot instead, stop the container
first:

```sh
docker compose stop web
cp -a data ./strong-data-$(date +%F)
docker compose start web
```

## Verify a backup

Check integrity before you need it:

```sh
sqlite3 ./strong-data-$(date +%F).sqlite3 'PRAGMA integrity_check'
```

The result should be `ok`; on a host without the `sqlite3` CLI, use the container:

```sh
docker run --rm -v "$PWD/strong-data-2026-01-05.sqlite3:/backup/backup.sqlite3:ro" \
  --entrypoint python strong-data:local \
  -c "import sqlite3; print(sqlite3.connect('/backup/backup.sqlite3').execute('PRAGMA integrity_check').fetchone()[0])"
```

Optionally restore into a separate installation and confirm sessions and exercises
are present.

## Restore

Restoring replaces the live database. Take a current backup first.

```sh
docker compose stop web
sudo cp ./strong-data-2026-01-05.sqlite3 data/strong.sqlite3
sudo chown 1000:1000 data/strong.sqlite3
sudo rm -f data/strong.sqlite3-wal data/strong.sqlite3-shm
docker compose start web
```

Replace `1000:1000` with your `PUID` and `PGID`. The `chown` matters because the
container is read-only and unprivileged and cannot fix ownership itself. Removing
the stale `-wal` and `-shm` sidecars matters because they belong to the database
you just replaced; leaving them can resurrect deleted rows.

The server applies migrations to the restored database automatically on start.
Confirm the restore succeeded:

```sh
docker compose exec -T web python manage.py check
docker compose exec -T web python tools/healthcheck.py
```

Then log in and verify your sessions, muscle-group corrections and tokens. If
anything is wrong, stop the app and restore the previous backup the same way.

## Schedule and retain

`data/` is an ordinary host directory, so any host backup tool works: restic,
borg, kopia, Vorta, a NAS snapshot task, or the Proxmox backup client. Because the
app must keep running, prefer the online backup command above on a timer, or a
filesystem snapshot of the `data` directory taken while the container is stopped.

Run backups on a schedule that matches how often you import, keep several dated
copies, and periodically exercise a clean restore. Tokens are scoped to the
database, so a restored database also restores token validity; revoke any token
you no longer trust after a restore. A backup also restores `STRONG_SECRET_KEY`
dependencies: keep the secret you used, or rotating the key logs every session out.
