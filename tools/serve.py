import os
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from waitress import serve

from strong_data.wsgi import application
from workouts import pending
from workouts.limits import MAX_REQUEST_BODY_BYTES

TRUSTED_PROXY = os.environ.get("STRONG_TRUSTED_PROXY", "").strip() or None
PORT = int(os.environ.get("STRONG_PORT", "8000"))

if TRUSTED_PROXY is None:
    raise SystemExit(
        "STRONG_TRUSTED_PROXY must be set to the reverse proxy address, or to * when the "
        "app is reachable only from a trusted container network. The example .env file "
        "ships *. Without it the proxy's X-Forwarded-Proto header is ignored and HTTPS "
        "form submissions fail CSRF checks."
    )


def verify_data_directory() -> None:
    directory = Path(settings.DATABASES["default"]["NAME"]).parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-probe"
        probe.touch()
        probe.unlink()
    except OSError as error:
        raise SystemExit(
            f"Cannot write to {directory}: {error}. The host directory behind the data mount "
            "must be owned by the UID and GID in PUID and PGID, for example "
            "sudo chown -R 1000:1000 data."
        ) from error


verify_data_directory()
call_command("migrate", interactive=False)
pending.start_sweeper(settings.PENDING_SWEEP_SECONDS)
serve(
    application,
    host="0.0.0.0",
    port=PORT,
    trusted_proxy=TRUSTED_PROXY,
    trusted_proxy_headers={"x-forwarded-proto"},
    clear_untrusted_proxy_headers=True,
    max_request_body_size=MAX_REQUEST_BODY_BYTES,
)
