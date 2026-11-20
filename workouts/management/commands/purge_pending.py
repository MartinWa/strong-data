from django.core.management.base import BaseCommand

from workouts import pending


class Command(BaseCommand):
    help = "Delete staged uploads whose preview has expired."

    def add_arguments(self, parser):
        parser.add_argument("--ttl", type=int, default=pending.PENDING_TTL_SECONDS)

    def handle(self, *args, **options):
        removed = pending.purge_stale(options["ttl"])
        label = "file" if removed == 1 else "files"
        self.stdout.write(f"Removed {removed} stale pending {label}.")
