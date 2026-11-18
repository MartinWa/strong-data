# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

COPY pyproject.toml uv.lock .python-version ./

RUN uv sync --frozen --no-install-project

COPY . .

RUN chmod +x tools/docker_start.sh \
    && mkdir -p /app/data /app/staticfiles \
    && chown -R app:app /app

USER app

RUN uv run python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python tools/healthcheck.py

CMD ["/app/tools/docker_start.sh"]
