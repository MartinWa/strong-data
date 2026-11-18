from tools.check_no_private_data import find_violations


def test_allows_source_and_synthetic_config_files():
    paths = [
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "src/app.py",
        "tests/parsing/test_parse.py",
        ".env.example",
    ]
    assert find_violations(paths) == []


def test_rejects_private_data_files():
    paths = [
        "export.csv",
        "data.sqlite3",
        "state.db",
        "state.db-wal",
        "dump.sql",
        "backup.sql.gz",
        "archive.zip",
        "secrets.env",
        ".env.local",
        "planning/PLAN.md",
        "reference/init.sql",
    ]
    assert find_violations(paths) == sorted(paths)
