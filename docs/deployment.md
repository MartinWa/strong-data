# Deployment

strong-data ships as a non-root container image and publishes no ports on its own:
run it behind a TLS-terminating reverse proxy. SQLite is the only datastore and
lives in a host directory mounted at `/app/data`.

## Requirements

- Docker Engine 24 or newer, with a current Docker Compose release
- a TLS-terminating reverse proxy (Caddy, nginx, Traefik, or a NAS proxy app)
- an `amd64` or `arm64` host

## Images

Released images are published to GHCR for `linux/amd64` and `linux/arm64`:

```sh
docker pull ghcr.io/martinwa/strong-data:latest
```

Pin a version (`ghcr.io/martinwa/strong-data:1.0.0`) or, better, a digest
(`ghcr.io/martinwa/strong-data@sha256:...`) for a deployment you do not want to
change underneath you. To build from a working copy instead:

```sh
docker build --target production -t strong-data:local .
# or let Compose do it, without touching the default deployment path:
docker compose -f compose.yaml -f compose.local-build.yaml up -d
```

`compose.local-build.yaml` always builds and tags `strong-data:local`, whatever
`STRONG_IMAGE` says, so it cannot quietly deploy a published image or overwrite a
release tag with local source.

## Configuration

`compose.yaml` reads its values from a private `.env` file next to it, or from the
shell when they are exported there. Three values have no usable default:

```sh
cp .env.example .env
# edit .env: set STRONG_SECRET_KEY and STRONG_ALLOWED_HOSTS
```

The third, `STRONG_TRUSTED_PROXY`, already ships as `*` in the example file, which is
correct when the container is reachable only from a trusted Docker network or a
loopback port. Production configuration is mandatory rather than optional: the
application refuses to start when `STRONG_SECRET_KEY` is missing or still the
`.env.example` placeholder, and the server refuses to start without
`STRONG_TRUSTED_PROXY`, so a copied example cannot be deployed by accident and a
hand-written file fails loudly instead of half-working.

| Variable | Default | Meaning |
| --- | --- | --- |
| `STRONG_SECRET_KEY` | none, required | Django secret. Generate one per installation: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. `STRONG_SECRET_KEY_FILE` reads the value from a file instead, for Docker or Podman secrets. |
| `STRONG_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated public hostnames the proxy forwards, e.g. `workouts.example.com`. Requests with any other `Host` are rejected. |
| `STRONG_TRUSTED_PROXY` | none, required | Address allowed to set forwarding headers. The example file ships `*`, which is correct when the container is reachable only from a trusted Docker network or a loopback port; set it to the proxy's container address to narrow it. The server refuses to start without a value, because `X-Forwarded-Proto` would otherwise be ignored and HTTPS form submissions would fail the CSRF origin check. |
| `STRONG_IMAGE` | `ghcr.io/martinwa/strong-data:latest` | Image tag or digest to deploy. |
| `STRONG_TIME_ZONE` | `UTC` | IANA zone name, e.g. `Europe/Stockholm`. Strong exports record wall-clock local time with no offset, so imports are interpreted in this zone and every date in the UI and API is rendered in it. It applies at import time: changing it later does not rewrite existing rows. |
| `PUID` / `PGID` | `1000` / `1000` | UID and GID the process runs as and that must own the `data` directory. |
| `STRONG_DEBUG` | `false` | Never enable on a public instance, and not passed by the production Compose file at all. With `false` the session and CSRF cookies are `Secure`, so the app must be served over HTTPS. |
| `STRONG_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated `https://` origins, only needed if the proxy rewrites the `Host` header. |
| `STRONG_UPDATE_CHECK` | `true` | Lets the footer ask GitHub for the latest stable release and show a dot when a newer one exists. Cached for six hours; never blocks page rendering. Set `false` for an installation that must make no outbound requests. |
| `STRONG_PENDING_SWEEP_SECONDS` | `900` | How often the server deletes staged uploads whose preview expired. `0` turns the background sweep off, for an installation that prefers an external `manage.py purge_pending` schedule. |
| `STRONG_PORT` | `8000` | Listen port inside the container. Not passed by the production Compose file; keep the default unless you also change the published port. |
| `STRONG_DB_PATH` | `/app/data/strong.sqlite3` | Set by the image. Override only when you mount the database somewhere else. |
| `STRONG_STATIC_ROOT` | `/app/staticfiles` | Where collected static files live. The image ships them and is read-only, so override only together with a writable volume. |
| `STRONG_NETWORK` | `strong-data` | Name of the Docker network Compose creates for the app. |
| `PROXY_NETWORK` | `proxy` | Existing proxy network to join, used only with `compose.proxy-network.yaml`. |
| `STRONG_HOST_PORT` | `8000` | Loopback port, used only with `compose.host-port.yaml`. |

The Compose file holds no defaults of its own: it passes the application variables
through untouched, so a value in `.env` (or exported in the shell) is what the
container sees, and an unset value falls back to the default in the table — except
the three with no default, which stop startup instead.
`STRONG_DB_PATH` and `STRONG_STATIC_ROOT` come from the image; `STRONG_DEBUG` and
`STRONG_PORT` are deliberately not passed. Compose merges a `compose.override.yaml`
next to `compose.yaml` automatically, which is the place to add anything extra:

```yaml
services:
  web:
    environment:
      - STRONG_DEBUG
      - STRONG_PORT
```

`docker compose config` prints the effective configuration, including which
variables are set.

## First start

The `data` directory is a bind mount, so the host owns it and backups are plain
files. Create it and give it to the same UID and GID the container runs as, or the
app cannot create the database:

```sh
mkdir -p data
sudo chown -R 1000:1000 data
cp .env.example .env
# edit .env: STRONG_SECRET_KEY, STRONG_ALLOWED_HOSTS, and STRONG_TIME_ZONE if you are not on UTC
docker compose up -d
docker compose logs -f web
```

On each start the container applies migrations and serves the app with waitress.
If the data directory is not writable, startup stops with an error that names the
directory and the `chown` that fixes it. Static files are collected into the image
at build time and served locally by WhiteNoise; nothing is fetched from a CDN. The
container runs read-only with all Linux capabilities dropped, on a tmpfs `/tmp`,
and its built-in health check calls `GET /api/v1/healthz` every 30 seconds:

```sh
docker compose ps
curl -fsS https://workouts.example.com/api/v1/healthz
```

Do not point the `data` directory at NFS or SMB: SQLite write-ahead logging is not
safe on network filesystems.

## Connecting a reverse proxy

Two patterns cover every common home lab setup. The application needs no
proxy-specific settings for either one.

### A proxy container on a shared Docker network (default)

Compose creates a network named `strong-data`. Attach your proxy container to it and
forward to `web:8000`:

```sh
docker network connect strong-data caddy
```

If your proxy already owns a private network that all your services join, use that
network instead. Its name is the only value you need:

```sh
docker network ls
echo 'PROXY_NETWORK=proxy' >> .env
docker compose -f compose.yaml -f compose.proxy-network.yaml up -d
```

### A proxy on the host

For a proxy installed on the host itself, such as a NAS reverse-proxy package or a
native nginx or Caddy, publish the port on loopback. It is never reachable from
outside the host:

```sh
docker compose -f compose.yaml -f compose.host-port.yaml up -d
```

Point the proxy at `http://127.0.0.1:8000` and set `STRONG_HOST_PORT` if 8000 is
taken. Do not bind the port to `0.0.0.0`.

Either way, terminate TLS at the proxy, keep the app unreachable from the public
network except through it, and raise the upload size limit only as far as needed
for the 10 MB upload limit. Set the forwarding header on every request:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    client_max_body_size 10m;
}
```

```caddyfile
workouts.example.com {
    reverse_proxy web:8000
}
```

```yaml
traefik.http.routers.strong-data.rule: Host(`workouts.example.com`)
traefik.http.services.strong-data.loadbalancer.server.port: "8000"
```

Caddy forwards `X-Forwarded-Proto` on its own; nginx and Traefik need it set
explicitly. Keep `.env` private: it is gitignored, excluded from the image build
context, and must never be committed.

## Administrator accounts

Signup is disabled. Create the first administrator after the stack is up:

```sh
docker compose exec web python manage.py createsuperuser
```

Users, muscle-group corrections and bearer tokens are all managed in the web UI
and remain scoped to their owner. See `docs/usage.md` and `docs/api.md`.

## Housekeeping

A CSV is staged on disk until it is confirmed or cancelled. Confirm and Cancel
delete it immediately, as does the next upload from the same browser; the sweep
catches what is left behind, deleting every staged file older than one hour. It
runs in two places: on a background thread in the server process every
`STRONG_PENDING_SWEEP_SECONDS` (default 900), starting once at boot, and at the
start of any request that reaches the upload, preview or sessions page.

`tools/serve.py` starts the thread, so the container sweeps itself and no timer,
cron job or extra service is needed or configured. The development server
(`runserver`) has no thread, and sweeps on request as it always did.

Set `STRONG_PENDING_SWEEP_SECONDS=0` to disable the thread and drive the sweep
yourself:

```sh
docker compose exec -T web python manage.py purge_pending [--ttl SECONDS]
```

Use `exec`, not `run`: pending files live in the container's `/tmp` tmpfs, which a
fresh container would not see. If you disable the thread, sweep at least as often
as a preview can live (one hour). An installation that mounts a volume at
`STRONG_PENDING_DIR` can run the command from any container instead.

## Auto-updates

The image carries no updater and no Watchtower label, so nothing restarts the app
behind your back. If you run Watchtower or Diun, opt this container in explicitly
in your own override file:

```yaml
services:
  web:
    labels:
      - com.centurylinklabs.watchtower.enable=true
```

## Verify and upgrade

Take a backup before upgrading (see `docs/backup-and-recovery.md`), update
`STRONG_IMAGE` to the new released tag, then:

```sh
docker compose up -d --pull always
```

`--pull always` matters: without it, Compose does not refresh an unchanged tag
such as `latest`. Migrations run automatically on start. To roll back, point
`STRONG_IMAGE` back to the previous tag and restore the database backup together.

## Ownership

The image runs as an unprivileged user and drops every Linux capability, so it can
never `chown` anything, inside the container or on the host. Ownership is therefore
a host concern: the `data` directory must belong to `PUID:PGID` (default
`1000:1000`). On a NAS where those IDs differ, set them and fix the directory once:

```sh
echo 'PUID=1026' >> .env
echo 'PGID=100' >> .env
docker compose down
sudo chown -R 1026:100 data
docker compose up -d
```

Restoring a backup is the same operation: stop the app, copy the file in, `chown` it
to `PUID:PGID`, start the app.

## Local development

`compose.development.yaml` is a standalone development stack. It builds the
`development` image target (which adds the test and lint toolchain), serves on
`127.0.0.1:8000` only, requires no `.env`, and keeps all state — database,
virtualenv, caches — on named volumes while your working copy is bind-mounted
into the container:

```sh
docker compose -f compose.development.yaml up --build
```

Dependency changes are picked up by rebuilding: the image seeds a fresh
virtualenv in the `development-state` volume whenever the locked dependency
fingerprint changes.
