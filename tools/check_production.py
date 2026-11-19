"""Verify the production image on disposable storage without external access."""

import importlib.util
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from strong_data.version import app_version


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def request(port, path, token=None):
    headers = {"Host": "127.0.0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    probe = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(probe, timeout=5) as response:
            return response.status, response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.headers


def wait_until_healthy(port, attempts=120):
    for _ in range(attempts):
        try:
            return request(port, "/api/v1/healthz")
        except OSError:
            time.sleep(0.5)
    raise AssertionError("The production server did not become healthy.")


def verify_running_as_non_root():
    if os.geteuid() == 0:
        raise AssertionError("The production image must run as a non-root user.")


def verify_dev_tooling_absent():
    for module in ("pip", "pytest"):
        assert importlib.util.find_spec(module) is None, module


def verify_version():
    version = app_version()
    expected = os.environ.get("EXPECTED_VERSION")
    if expected:
        assert version == expected, (version, expected)
    return version


def verify_serving(database):
    port = free_port()
    child = subprocess.Popen(
        [sys.executable, "-m", "tools.serve"],
        env={
            **os.environ,
            "STRONG_SECRET_KEY": "synthetic-production-check-key-never-for-runtime-0000000",
            "STRONG_ALLOWED_HOSTS": "127.0.0.1",
            "STRONG_DB_PATH": str(database),
            "STRONG_PORT": str(port),
            "STRONG_TRUSTED_PROXY": "*",
        },
    )
    try:
        status, headers = wait_until_healthy(port)
        assert status == 200, status
        assert headers.get("Cache-Control") == "no-store", headers.get("Cache-Control")
        status, _ = request(port, "/api/v1/me")
        assert status == 401, status
        status, _ = request(port, "/")
        assert status in (200, 301, 302), status
    finally:
        child.terminate()
        child.wait(timeout=30)
    with sqlite3.connect(database) as connection:
        migrated = connection.execute("SELECT COUNT(*) FROM django_migrations").fetchone()[0]
    assert migrated > 0, migrated


def verify_refuses_unsafe_secret():
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"STRONG_SECRET_KEY", "STRONG_DEBUG"}
    }
    result = subprocess.run(
        [sys.executable, "-c", "import strong_data.settings"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, "The production image started without a secret key."
    assert b"STRONG_SECRET_KEY" in result.stderr, result.stderr


def main():
    verify_running_as_non_root()
    verify_dev_tooling_absent()
    verify_refuses_unsafe_secret()
    version = verify_version()
    data = Path(tempfile.mkdtemp(prefix="strong-data-production-check-"))
    verify_serving(data / "strong.sqlite3")
    print(f"Verified non-root startup, automatic migrations and HTTP serving for {version}.")


if __name__ == "__main__":
    main()
