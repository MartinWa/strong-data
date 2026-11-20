def use_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    if ":memory:" in str(connection.settings_dict["NAME"]):
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
