import pytest
from django.db import connection

from strong_data.db import use_sqlite_wal


class MemoryConnection:
    vendor = "sqlite"
    settings_dict = {"NAME": ":memory:"}

    def cursor(self):
        raise AssertionError("an in-memory database has no journal to convert")


class PostgresConnection:
    vendor = "postgresql"
    settings_dict = {"NAME": "app"}

    def cursor(self):
        raise AssertionError("only SQLite connections are touched")


def test_wal_is_skipped_for_in_memory_databases():
    use_sqlite_wal(None, MemoryConnection())


def test_wal_is_skipped_for_other_vendors():
    use_sqlite_wal(None, PostgresConnection())


@pytest.mark.django_db
def test_the_test_database_still_serves_queries():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")

        assert cursor.fetchone() == (1,)
