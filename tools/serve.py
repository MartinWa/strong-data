import os

from django.conf import settings
from django.core.management import call_command
from waitress import serve

from strong_data.wsgi import application
from workouts import pending

TRUSTED_PROXY = os.environ.get("STRONG_TRUSTED_PROXY", "").strip() or None
PORT = int(os.environ.get("STRONG_PORT", "8000"))

call_command("migrate", interactive=False)
pending.start_sweeper(settings.PENDING_SWEEP_SECONDS)
serve(
    application,
    host="0.0.0.0",
    port=PORT,
    trusted_proxy=TRUSTED_PROXY,
    trusted_proxy_headers={"x-forwarded-proto"},
    clear_untrusted_proxy_headers=True,
)
