from pathlib import Path

from tools.check_no_private_data import find_violations

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_rejects_sqlite_sidecar_files():
    paths = [
        "db.sqlite3-wal",
        "db.sqlite3-shm",
        "db.sqlite3-journal",
        "state.db-wal",
        "cache.sqlite-shm",
    ]
    assert find_violations(paths) == sorted(paths)


def test_ignore_rules_cover_sqlite_sidecars():
    for ignore_file in (".gitignore", ".dockerignore"):
        path = REPO_ROOT / ignore_file
        if path.is_file():
            patterns = path.read_text(encoding="utf-8").splitlines()
            assert "*.sqlite3-*" in patterns


def test_production_compose_requires_env_file():
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "path: .env" in text
    assert "required: true" in text


def test_development_compose_makes_env_file_optional():
    text = (REPO_ROOT / "compose.development.yaml").read_text(encoding="utf-8")

    assert "env_file: !reset" in text
    assert "path: .env" in text
    assert "required: false" in text


def test_restore_docs_create_container_before_copying_backup():
    text = (REPO_ROOT / "docs/backup-and-recovery.md").read_text(encoding="utf-8")

    create = text.index("docker compose create web")
    copy = text.index("docker compose cp ./backup.sqlite3")
    assert create < copy
    assert "cp .env.example .env" in text[:create]
    assert "docker compose build web" in text[:create]
