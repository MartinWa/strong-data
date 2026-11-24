# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv-tool

# Apply Debian fixes to inherited packages before building development or production.
FROM python:3.14.10-slim-bookworm@sha256:e60ad028afdcdd14772a3d46decf0eaf616720f9102aeb4397a2045ff6718c3d AS os-base
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

FROM os-base AS requirements-export
COPY --from=uv-tool /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never
WORKDIR /tmp/dependencies
COPY pyproject.toml uv.lock ./
RUN uv export --locked --no-dev --no-emit-project --format requirements-txt \
      --output-file /tmp/requirements.txt \
    && uv export --locked --only-group dev --no-emit-project --format requirements-txt \
      --output-file /tmp/requirements-dev.txt

FROM os-base AS python-build
COPY --from=requirements-export /tmp/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes --prefix=/opt/python \
      -r /tmp/requirements.txt

FROM os-base AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=python-build /opt/python /usr/local
WORKDIR /app

FROM runtime-base AS development
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git config --system --add safe.directory /app \
    && rm -rf /var/lib/apt/lists/*
COPY --from=requirements-export /tmp/requirements-dev.txt /opt/requirements-dev.txt
RUN python -m venv --system-site-packages /state/venv \
    && /state/venv/bin/python -m pip install --no-cache-dir --require-hashes --no-deps \
       -r /opt/requirements-dev.txt \
    && mv /state/venv /opt/venv-seed \
    && tar -C /opt/venv-seed -cf - . | sha256sum > /opt/venv-seed.sha256 \
    && useradd --uid 1000 --create-home developer \
    && mkdir -p /state/development /state/tmp && chown -R 1000:1000 /state
ENV PATH=/state/venv/bin:$PATH \
    STRONG_DEBUG=true \
    STRONG_DB_PATH=/state/development/strong.sqlite3 \
    STRONG_STATIC_ROOT=/state/staticfiles \
    TMPDIR=/state/tmp \
    RUFF_CACHE_DIR=/state/ruff-cache \
    PYTEST_ADDOPTS="-o cache_dir=/state/pytest-cache" \
    PIP_REQUIRE_VIRTUALENV=true
COPY tools/dev_entrypoint.py /usr/local/bin/strong-data-dev.py
COPY . /app
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/python", "/usr/local/bin/strong-data-dev.py"]
CMD ["sh", "-c", "python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]

# A plain build produces the production image.
FROM runtime-base AS production
ARG STRONG_VERSION=development
ENV STRONG_VERSION=${STRONG_VERSION} \
    STRONG_DB_PATH=/app/data/strong.sqlite3
RUN python -m pip uninstall --yes pip \
    && mkdir -p /app/data && chown 1000:1000 /app/data
COPY manage.py /app/manage.py
COPY strong_data /app/strong_data
COPY api /app/api
COPY parsing /app/parsing
COPY workouts /app/workouts
COPY templates /app/templates
COPY LICENSE NOTICE /app/
COPY tools/__init__.py tools/check_production.py tools/healthcheck.py tools/serve.py /app/tools/
RUN STRONG_SECRET_KEY=synthetic-build-key-never-for-runtime-000000000000 \
    python manage.py collectstatic --noinput
USER 1000:1000
RUN STRONG_SECRET_KEY=synthetic-build-key-never-for-runtime-000000000000 \
    python -c "from strong_data.wsgi import application; assert application"
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python tools/healthcheck.py
CMD ["python", "-m", "tools.serve"]
