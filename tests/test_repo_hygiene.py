from pathlib import Path

from tools.check_no_private_data import candidate_files, content_violations, find_violations

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


def test_production_compose_requires_operator_configuration():
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'image: "${STRONG_IMAGE:?Set a tested local or released image tag or digest}"' in text
    assert 'env_file: "${STRONG_ENV_FILE:-.env}"' in text
    assert 'name: "${PROXY_NETWORK:?Set the existing private proxy network}"' in text


def test_production_compose_hardens_the_container():
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")

    for hardening in ("external: true", "read_only: true", "cap_drop", "no-new-privileges:true"):
        assert hardening in text


def test_development_compose_needs_no_env_file():
    text = (REPO_ROOT / "compose.development.yaml").read_text(encoding="utf-8")

    assert "env_file" not in text
    assert "target: development" in text
    assert "127.0.0.1:8000:8000" in text


def test_restore_docs_create_container_before_copying_backup():
    text = (REPO_ROOT / "docs/backup-and-recovery.md").read_text(encoding="utf-8")

    create = text.index("docker compose create web")
    copy = text.index("docker compose cp ./backup.sqlite3")
    assert create < copy
    assert "cp .env.example .env" in text[:create]
    assert "docker compose build web" in text[:create]


def test_recovery_chown_commands_grant_only_ownership():
    for document in ("docs/backup-and-recovery.md", "docs/deployment.md"):
        text = (REPO_ROOT / document).read_text(encoding="utf-8")

        assert "--user 0:0 --cap-add CHOWN web chown" in text


def test_content_scan_flags_private_content(tmp_path):
    sample = tmp_path / "notes.md"
    email = "real.person" + "@" + "corp.example"
    access_key = "AKIA" + "IOSFODNN7EXAMPLE"
    host_path = "C:" + "\\Users\\someone\\export.csv"
    sample.write_text(f"contact {email}\nkey {access_key}\npath {host_path}\n", encoding="utf-8")

    findings = content_violations([str(sample)])

    assert findings == [
        f"{sample}:1: email address",
        f"{sample}:2: AWS access key",
        f"{sample}:3: absolute host path",
    ]


def test_content_scan_allows_synthetic_examples(tmp_path):
    sample = tmp_path / "notes.md"
    sample.write_text(
        "user@example.com\n"
        "https://workouts.example.com/api/v1/healthz\n"
        "editor-home:/home/developer\n",
        encoding="utf-8",
    )

    assert content_violations([str(sample)]) == []


def test_repository_content_is_clean():
    assert content_violations(candidate_files()) == []
