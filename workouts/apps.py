from django.apps import AppConfig
from django.db.backends.signals import connection_created

from strong_data.db import use_sqlite_wal


class WorkoutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "workouts"

    def ready(self):
        connection_created.connect(use_sqlite_wal)
