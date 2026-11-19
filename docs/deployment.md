# Deployment

strong-data ships as a non-root container image. It publishes **no ports**: run it
behind a TLS-terminating reverse proxy on a private Docker network. SQLite is the
only datastore and lives in a named volume.

## Image and configuration

Either pull a tested release image or build one locally:

```sh
docker pull ghcr.io/martinwa/strong-data:latest
# or
docker build --target production -t strong-data:local .
```

Released images are built for `linux/amd64` only. On ARM hosts, build the image
locally with `docker build --target production` (or run the amd64 image under
emulation).

Compose resolves the image and the proxy network from the environment, so both are
recorded in the private `.env` file. Production configuration is mandatory: the base
`compose.yaml` requires `.env` and refuses to start without it, and the application
itself refuses to start when `STRONG_DEBUG` is unset or false unless
`STRONG_SECRET_KEY` holds a real value. The development fallback and the
`.env.example` placeholder are both rejected, so a copied example file cannot be
deployed by accident. Copy the example environment file and fill in real values
before the first start:

```sh
cp .env.example .env
```

| Variable | Meaning |
| --- | --- |
| `STRONG_IMAGE` | Image tag or digest to deploy: a released GHCR tag (`ghcr.io/martinwa/strong-data:1.0.0`), `ghcr.io/martinwa/strong-data@sha256:...`, or a locally built tag such as `strong-data:local`. |
| `PROXY_NETWORK` | Name of the existing private Docker network your TLS reverse proxy is attached to. |
| `STRONG_SECRET_KEY` | Django secret. Required: startup fails if it is missing or still the `.env.example` placeholder. Generate a fresh one per installation: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `STRONG_DEBUG` | `false` in production. Never leave it enabled on a public instance. |
| `STRONG_ALLOWED_HOSTS` | Comma-separated public hostnames the proxy forwards, e.g. `workouts.example.com`. |
| `STRONG_DB_PATH` | SQLite path inside the container; keep the default `/app/data/strong.sqlite3` so it lands on the data volume. |
| `STRONG_STATIC_ROOT` | Where collected static files live (the image ships them at `/app/staticfiles`). Override only for special setups. |
| `STRONG_PENDING_DIR` | Where previewed-but-unconfirmed uploads are staged. Defaults to `/tmp/strong-data-pending`, which lands on the container's `/tmp` tmpfs; override only if you mount a dedicated volume. |
| `STRONG_CSRF_TRUSTED_ORIGINS` | Comma-separated `https://` origins, only needed if the proxy rewrites the `Host` header. |
| `STRONG_UPDATE_CHECK` | `true` (default) lets the footer ask GitHub for the latest stable release and show a dot when a newer one exists. The answer is cached for six hours and the request never blocks page rendering. Set `false` for an installation that must make no outbound requests. |
| `STRONG_PORT` | Listen port inside the container (default `8000`). |
| `STRONG_TRUSTED_PROXY` | Address allowed to set forwarding headers. No default: without it, `X-Forwarded-Proto` is ignored and HTTPS form submissions fail the CSRF origin check. Set it to the proxy's container address, or to `*` when the app is reachable only from the proxy network (the example file ships `*`). |

Waitress trusts `X-Forwarded-Proto` from that address so Django sees `https` and
HTTPS form submissions pass CSRF origin checks. Set the header on every forwarded
request. Because the default is empty, a deployment that forgets this variable
fails closed: the app still serves, but HTTPS form submissions are rejected rather
than silently trusting a spoofed header. Keep `.env` private: it is gitignored, excluded from the image build
context, and must never be committed.

## Start

```sh
docker compose up -d
```

On each start the container applies migrations and serves the app with waitress.
Static files are collected into the image at build time and served locally by
WhiteNoise; nothing is fetched from a CDN. The container runs read-only with all
Linux capabilities dropped, on a tmpfs `/tmp`, and its built-in health check calls
`GET /api/v1/healthz` every 30 seconds:

```sh
docker compose ps
docker compose logs -f web
```

## Reverse proxy

The `web` service joins a pre-existing proxy network and is reachable from other
containers on that network at `web:8000`. Put your own TLS proxy on the same
network and forward to it. A minimal nginx location block looks like this:

```nginx
location / {
    proxy_pass http://web:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    client_max_body_size 10m;
}
```

Terminate TLS at the proxy, keep the app unreachable from the public network
except through it, and raise `client_max_body_size` only as needed for the 10 MB
upload limit. Do not publish port 8000 on the host.

## Administrator accounts

Signup is disabled. Create the first administrator after the stack is up:

```sh
docker compose exec web python manage.py createsuperuser
```

Users, muscle-group corrections and bearer tokens are all managed in the web UI
and remain scoped to their owner. See `docs/usage.md` and `docs/api.md`.

## Verify and upgrade

```sh
curl -fsS https://workouts.example.com/api/v1/healthz
```

Take a backup before upgrading (see `docs/backup-and-recovery.md`), update
`STRONG_IMAGE` to the new released tag, then:

```sh
docker compose up -d
```

Migrations run automatically on start. To roll back, point `STRONG_IMAGE` back to
the previous image tag and restore the database backup together.

### Upgrading from pre-release images

Databases created by images built before the non-root UID was fixed at 1000 are
owned by a different, system-chosen UID, so write access to the existing data
volume is lost after upgrading. Run a one-time ownership migration with only
the ownership capability granted, while the service is stopped:

```sh
docker compose stop web
docker compose run --rm --user 0:0 --cap-add CHOWN web chown -R 1000:1000 /app/data
docker compose up -d
```

If the app fails with a database permission error right after an upgrade, this
migration is the fix; it is idempotent and never needed for fresh data volumes.

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
