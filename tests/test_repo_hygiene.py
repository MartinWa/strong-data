import re
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


def test_production_compose_ships_working_defaults():
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'image: "${STRONG_IMAGE:-ghcr.io/martinwa/strong-data:latest}"' in text
    assert 'user: "${PUID:-1000}:${PGID:-1000}"' in text
    assert "- ./data:/app/data" in text
    assert 'name: "${STRONG_NETWORK:-strong-data}"' in text
    assert "env_file" not in text
    assert "build:" not in text


def test_production_compose_passes_application_variables_through():
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")
    environment = text[text.index("    environment:") : text.index("    volumes:")]

    for name in (
        "STRONG_SECRET_KEY",
        "STRONG_ALLOWED_HOSTS",
        "STRONG_TRUSTED_PROXY",
        "STRONG_TIME_ZONE",
        "STRONG_SECRET_KEY_FILE",
        "STRONG_CSRF_TRUSTED_ORIGINS",
        "STRONG_UPDATE_CHECK",
        "STRONG_PENDING_SWEEP_SECONDS",
    ):
        assert f"      - {name}\n" in environment
    assert "${" not in environment
    assert "STRONG_DEBUG" not in text
    assert "STRONG_PORT" not in text


def test_production_compose_hardens_the_container():
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")

    for hardening in ("read_only: true", "cap_drop", "no-new-privileges:true", "init: true"):
        assert hardening in text


def test_optional_overrides_cover_the_documented_patterns():
    host_port = (REPO_ROOT / "compose.host-port.yaml").read_text(encoding="utf-8")
    proxy_network = (REPO_ROOT / "compose.proxy-network.yaml").read_text(encoding="utf-8")
    local_build = (REPO_ROOT / "compose.local-build.yaml").read_text(encoding="utf-8")

    assert '"127.0.0.1:${STRONG_HOST_PORT:-8000}:8000"' in host_port
    assert "external: true" in proxy_network
    assert 'name: "${PROXY_NETWORK:?Set the existing private proxy network}"' in proxy_network
    assert "image: strong-data:local" in local_build
    assert "pull_policy: build" in local_build
    assert "target: production" in local_build
    assert "STRONG_IMAGE" not in local_build


def test_required_settings_are_documented_consistently():
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    deployment = (REPO_ROOT / "docs/deployment.md").read_text(encoding="utf-8")

    assert example[:3] == [
        "STRONG_SECRET_KEY=replace-with-a-long-random-value",
        "STRONG_ALLOWED_HOSTS=workouts.example.com",
        "STRONG_TRUSTED_PROXY=*",
    ]
    for required in ("STRONG_SECRET_KEY", "STRONG_TRUSTED_PROXY"):
        assert f"| `{required}` | none, required |" in deployment
    assert "| `STRONG_ALLOWED_HOSTS` |" in deployment


def test_release_tagging_is_scripted():
    script = (REPO_ROOT / "tools/tag_release.ps1").read_text(encoding="utf-8")

    assert "Switch to main before creating a release tag." in script
    assert "Commit or stash working-tree changes" in script
    assert "tag -a $Version" in script
    assert "refs/tags/$Version" in script


def test_published_package_must_be_publicly_pullable():
    text = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "ghcr.io/token?scope=repository" in text
    assert "-f visibility=public" in text
    assert "secrets.PACKAGE_TOKEN || github.token" in text
    assert "it is not public" not in text


def test_release_checks_and_attests_each_platform():
    text = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "platforms: linux/amd64" in text
    assert "platforms: linux/arm64" in text
    assert text.count("push-by-digest=true") == 2
    assert text.count("bash tools/check_release_image.sh") == 2
    assert "sbom-amd64.spdx.json" in text
    assert "sbom-arm64.spdx.json" in text


def test_contributor_agreement_allows_commercial_relicensing():
    text = (REPO_ROOT / "CLA.md").read_text(encoding="utf-8")

    assert "You retain ownership of the copyright" in text
    assert "sublicense and distribute" in text
    assert "right to relicense" in text
    assert "## 6. Corporate contributions" in text
    assert "harmonyagreements.org" in text
    assert "## 13. Signature records" in text
    assert "the owner of the `MartinWa/strong-data` GitHub repository" in text
    assert "the laws of Sweden" in text
    assert re.search(r"\[[A-Z][A-Z _]*\]", text) is None


def test_contributor_agreement_is_enforced_without_an_archived_action():
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    workflows = [
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / ".github/workflows").glob("*.yml")
    ]

    assert "Contributor License Agreement" in contributing
    assert "cla-assistant.io" in contributing
    assert not any("contributor-assistant/github-action" in text for text in workflows)
    assert not (REPO_ROOT / "signatures").exists()


def test_example_environment_lists_no_dead_settings():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    for dead in ("STRONG_ENV_FILE", "STRONG_DB_PATH", "STRONG_STATIC_ROOT"):
        assert dead not in text
    assert "STRONG_SECRET_KEY=" in text
    assert "STRONG_ALLOWED_HOSTS=" in text


def test_production_entrypoint_starts_the_pending_sweeper():
    text = (REPO_ROOT / "tools/serve.py").read_text(encoding="utf-8")

    assert "pending.start_sweeper(settings.PENDING_SWEEP_SECONDS)" in text


def test_production_body_cap_probe_derives_from_the_configured_cap():
    text = (REPO_ROOT / "tools/check_production.py").read_text(encoding="utf-8")

    assert "max_request_body_size=MAX_REQUEST_BODY_BYTES" in (
        REPO_ROOT / "tools/serve.py"
    ).read_text(encoding="utf-8")
    assert "OVERSIZED_BODY_BYTES = MAX_REQUEST_BODY_BYTES + 1" in text


def test_development_compose_needs_no_env_file():
    text = (REPO_ROOT / "compose.development.yaml").read_text(encoding="utf-8")

    assert "env_file" not in text
    assert "target: development" in text
    assert "127.0.0.1:8000:8000" in text


def test_restore_docs_stop_copy_rechown_and_start():
    text = (REPO_ROOT / "docs/backup-and-recovery.md").read_text(encoding="utf-8")
    restore = text[text.index("## Restore") :]

    stop = restore.index("docker compose stop web")
    copy = restore.index("sudo cp ./strong-data-")
    chown = restore.index("sudo chown 1000:1000 data/strong.sqlite3")
    start = restore.index("docker compose start web")
    assert stop < copy < chown < start
    assert "strong.sqlite3-wal" in restore


def test_backup_verification_reads_the_copy_immutably():
    text = (REPO_ROOT / "docs/backup-and-recovery.md").read_text(encoding="utf-8")
    verify = text[text.index("## Verify a backup") : text.index("## Restore")]

    assert "mode=ro&immutable=1" in verify
    assert "uri=True" in verify
    assert "strong-data:local" in verify
    assert "ghcr.io/" in verify


def test_ownership_is_fixed_on_the_host_never_in_a_root_container():
    for document in ("docs/backup-and-recovery.md", "docs/deployment.md"):
        text = (REPO_ROOT / document).read_text(encoding="utf-8")

        assert "--cap-add CHOWN" not in text
        assert "sudo chown" in text


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


def test_content_scan_honours_the_allow_marker(tmp_path):
    sample = tmp_path / "notes.md"
    email = "real.person" + "@" + "corp.example"
    sample.write_text(f"contact {email}  <!-- hygiene: allow -->\n", encoding="utf-8")

    assert content_violations([str(sample)]) == []


def test_repository_content_is_clean():
    assert content_violations(candidate_files()) == []
