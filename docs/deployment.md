# Deployment

strong-data ships as a non-root container image. It publishes **no ports**: run it
behind a TLS-terminating reverse proxy on the same Docker network. SQLite is the
only datastore and lives in a named volume.

## Build and configuration

Compose builds the image from the `Dockerfile`. Copy the example environment file
and fill in real values before the first start:

```sh
cp .env.example .env
```

| Variable | Meaning |
| --- | --- |
| `STRONG_SECRET_KEY` | Django secret. Generate a fresh one per installation: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `STRONG_DEBUG` | `false` in production. Never leave it enabled on a public instance. |
| `STRONG_ALLOWED_HOSTS` | Comma-separated public hostnames the proxy forwards, e.g. `workouts.example.com`. |
| `STRONG_DB_PATH` | SQLite path inside the container; keep the default `/app/data/strong.sqlite3` so it lands on the data volume. |
| `STRONG_CSRF_TRUSTED_ORIGINS` | Comma-separated `https://` origins, only needed if the proxy rewrites the `Host` header. |
| `STRONG_PORT` | Listen port inside the container (default `8000`). |

The application trusts the proxy's `X-Forwarded-Proto: https` header, so set it on
every forwarded request. Keep `.env` private: it is gitignored, excluded from the
image build context, and must never be committed.

## Start

```sh
docker compose up -d --build
```

On each start the container applies migrations and serves the app with waitress.
Static files are collected into the image at build time and served locally by
WhiteNoise; nothing is fetched from a CDN. The image's health check calls
`GET /api/v1/healthz` every 30 seconds:

```sh
docker compose ps
docker compose logs -f web
```

## Reverse proxy

The `web` service only `expose`s port 8000 to other containers. Put your own TLS
proxy on the same Compose network and forward to `http://web:8000`. A minimal
nginx location block looks like this:

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
docker compose exec -T web uv run python manage.py createsuperuser
```

Users, muscle-group corrections and bearer tokens are all managed in the web UI
and remain scoped to their owner. See `docs/usage.md` and `docs/api.md`.

## Verify and upgrade

```sh
curl -fsS https://workouts.example.com/api/v1/healthz
```

Take a backup before upgrading (see `docs/backup-and-recovery.md`), then rebuild:

```sh
docker compose up -d --build
```

Migrations run automatically on start. To roll back, restore the previous image
tag and database backup together.

## Local development

`compose.development.yaml` is an overlay that enables debug mode, binds the dev
server to `127.0.0.1:8000` only, and needs no `.env` (dependencies come from
`uv sync` during the image build):

```sh
uv sync --frozen
docker compose -f compose.yaml -f compose.development.yaml up --build
```
