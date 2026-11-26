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
shell when they are exported there. `.env.example` is the copyable list, with the
three values that have no usable default at the top: `STRONG_SECRET_KEY`,
`STRONG_ALLOWED_HOSTS` and `STRONG_TRUSTED_PROXY`. The example already sets
`STRONG_TRUSTED_PROXY=*`, which is correct when the container is reachable only
from a trusted Docker network or a loopback port.

Production configuration fails loudly rather than half-working: the application
refuses to start when `STRONG_SECRET_KEY` is missing or still the placeholder from
`.env.example`, and the server refuses to start without `STRONG_TRUSTED_PROXY`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `STRONG_SECRET_KEY` | none, required | Django secret. Generate one per installation: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. `STRONG_SECRET_KEY_FILE` reads the value from a file instead, for Docker or Podman secrets. |
| `STRONG_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated public hostnames the proxy forwards, e.g. `workouts.example.com`. Requests with any other `Host` are rejected. |
| `STRONG_TRUSTED_PROXY` | none, required | Address allowed to set forwarding headers. Use `*` when the container is reachable only from a trusted Docker network or a loopback port, or the proxy's container address to narrow it. Without it `X-Forwarded-Proto` is ignored and HTTPS form submissions fail the CSRF origin check. With a specific address (not `*`, not empty) the app also honors the proxy's `X-Forwarded-Proto` itself (`SECURE_PROXY_SSL_HEADER`); with `*` it does not, and the server prints a warning at startup when `STRONG_HOST_PORT` also publishes the port on the host, because then any client that can reach the port can spoof forwarding headers. |
| `STRONG_IMAGE` | `ghcr.io/martinwa/strong-data:latest` | Image tag or digest to deploy. |
| `STRONG_TIME_ZONE` | `UTC` | IANA zone name, e.g. `Europe/Stockholm`. Strong exports record wall-clock local time with no offset, so imports are interpreted in this zone and every date in the UI and API is rendered in it. It applies at import time: changing it later does not rewrite existing rows. |
| `PUID` / `PGID` | `1000` / `1000` | UID and GID the process runs as and that must own the `data` directory. |
| `STRONG_DEBUG` | `false` | Never enable on a public instance, and not passed by the production Compose file at all. With `false` the session and CSRF cookies are `Secure`, so the app must be served over HTTPS. |
| `STRONG_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated `https://` origins, only needed if the proxy rewrites the `Host` header. |
| `STRONG_UPDATE_CHECK` | `true` | Lets the footer ask GitHub for the latest stable release and show a dot when a newer one exists. Cached for six hours; never blocks page rendering. Set `false` for an installation that must make no outbound requests. |
| `STRONG_PENDING_SWEEP_SECONDS` | `900` | How often the server deletes staged uploads whose preview expired. `0` turns the background sweep off, for an installation that prefers an external `manage.py purge_pending` schedule. |
| `STRONG_PORT` | `8000` | Listen port inside the container. Leave it alone: `compose.host-port.yaml` publishes container port 8000, and the production Compose file passes no value for it. |
| `STRONG_DB_PATH` | `/app/data/strong.sqlite3` | Set by the image. Override only when you mount the database somewhere else. |
| `STRONG_STATIC_ROOT` | `/app/staticfiles` | Where collected static files live. The image ships them and is read-only, so override only together with a writable volume. |
| `STRONG_NETWORK` | `strong-data` | Name of the Docker network Compose creates for the app. |
| `PROXY_NETWORK` | `proxy` | Existing proxy network to join, used only with `compose.proxy-network.yaml`. |
| `STRONG_HOST_PORT` | `8000` | Loopback port, used only with `compose.host-port.yaml`. |

The production Compose file passes application variables through untouched and
defaults only the image, the user and the network name, so a value in `.env` (or
exported in the shell) is what the container sees. `STRONG_DB_PATH` and
`STRONG_STATIC_ROOT` come from the image; `STRONG_DEBUG` and `STRONG_PORT` are
deliberately not passed. Compose merges a `compose.override.yaml` next to
`compose.yaml` automatically, which is the place to add anything extra:

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

If the data directory is not writable, startup stops with an error that names the
directory and the `chown` that fixes it. Create the first account next.

The server sets `umask 0077` before it opens the database, so `strong.sqlite3` and
its `-wal` / `-shm` sidecar files are created with mode `0600`: readable and
writable only by the user the container runs as.

On each start the container applies migrations and serves the app with waitress.
Static files are collected into the image at build time and served locally by
WhiteNoise; nothing is fetched from a CDN. The container runs read-only with all
Linux capabilities dropped, on a tmpfs `/tmp`, and its built-in health check calls
`GET /api/v1/healthz` every 30 seconds:

```sh
docker compose ps
curl -fsS https://workouts.example.com/api/v1/healthz
```

Do not point the `data` directory at NFS or SMB: SQLite write-ahead logging is not
safe on network filesystems.

## Accounts

Signup is disabled and there is no self-service password reset, so every account
is created by an administrator. Create the first one once the stack is up:

```sh
docker compose exec web python manage.py createsuperuser
```

It prompts for a username, e-mail and password. For a scripted setup, pass the
password in the environment and give the e-mail explicitly: `--noinput` needs a
value for every required field, and an empty one is allowed.

```sh
docker compose exec -e DJANGO_SUPERUSER_PASSWORD='<password>' web \
  python manage.py createsuperuser --noinput --username <name> --email ''
```

Sign in at `/accounts/login/`. This account is an administrator: a superuser sees
every account's sessions in `/admin/`. Use it to create the people who import
their own workouts, under **Authentication and Authorization → Users** in
`/admin/`, leaving **Staff status** and **Superuser status** unchecked — an
ordinary account needs neither to log in and use the app. Only superusers can add
users, so keep `createsuperuser` for administrators.

Every account is separate: each one imports its own CSV, keeps its own
muscle-group corrections and API tokens, and never sees another account's data
outside the admin.

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

### Proxy settings

Terminate TLS at the proxy, keep the app unreachable from the public network
except through it, and raise the proxy's upload size limit only as far as needed
for the 10 MB upload limit. Forward the original `Host` and the client's
`X-Forwarded-Proto` on every request:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    client_max_body_size 10m;
}
```

Caddy forwards `X-Forwarded-Proto` on its own, so this is enough for it:

```caddyfile
workouts.example.com {
    reverse_proxy web:8000
}
```

nginx and Traefik need the header set explicitly. The app enforces the upload
limit on its own side too: the server refuses request bodies above 11 MB before
reading them, so a proxy that forgets its own limit cannot be used to fill the
container's temporary storage. Keep `.env` private: it is gitignored, excluded
from the image build context, and must never be committed.

Prefer naming the proxy's own address in `STRONG_TRUSTED_PROXY` over `*`: with a
specific address the app also trusts the forwarded `X-Forwarded-Proto` at the
Django layer, so HTTPS form submissions pass the CSRF origin check no matter how
the proxy is wired. With `*` that header is ignored by the app, and if
`STRONG_HOST_PORT` publishes the port on the host at the same time, startup
prints a loud warning on stderr: publish the port on `127.0.0.1` only, never on
`0.0.0.0`.

### Rate limiting

The app ships no rate limiter of its own, so put one on the two unauthenticated
entry points in the reverse proxy — `/accounts/login/` and `/admin/`. For nginx:

```nginx
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;

location = /accounts/login/ {
    limit_req zone=auth burst=5 nodelay;
    proxy_pass http://127.0.0.1:8000;
}
location /admin/ {
    limit_req zone=auth burst=5 nodelay;
    proxy_pass http://127.0.0.1:8000;
}
```

Caddy (`rate_limit` in the site block) and Traefik do the same; the exact
directive differs per proxy, but the two paths above are the ones worth limiting.

## Housekeeping

A CSV is staged on disk until it is confirmed or cancelled, which deletes it
immediately, as does the next upload from the same browser. The sweep catches what
is left behind: it deletes every staged file older than one hour, runs in the
server process every `STRONG_PENDING_SWEEP_SECONDS` (default 900, starting at
boot), and also runs at the start of any request that reaches the upload, preview
or sessions page.

Set `STRONG_PENDING_SWEEP_SECONDS=0` to disable the thread and sweep yourself:

```sh
docker compose exec -T web python manage.py purge_pending [--ttl SECONDS]
```

Use `exec`, not `run`: pending files live in the container's `/tmp` tmpfs, which a
fresh container would not see. An installation that mounts a volume at
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

Take a backup before upgrading (see [backup-and-recovery.md](backup-and-recovery.md)),
update `STRONG_IMAGE` to the new released tag, then:

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
