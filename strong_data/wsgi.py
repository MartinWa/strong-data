"""WSGI config for the strong-data project."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "strong_data.settings")

application = get_wsgi_application()
