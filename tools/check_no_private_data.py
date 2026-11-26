"""Fail when private data is tracked by git, by name or by content.

A line that legitimately needs to look like private data (for example a security
contact address) can opt out of the content scan by carrying the marker
``hygiene: allow``.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

BAD_SUFFIXES = (
    ".7z",
    ".bak",
    ".backup",
    ".csv",
    ".db",
    ".dump",
    ".env",
    ".gz",
    ".sql",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".zip",
)
BAD_DIRECTORIES = frozenset({"planning", "reference"})
MAX_SCAN_BYTES = 2 * 1024 * 1024
ALLOW_MARKER = "hygiene: allow"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_METADATA_CHUNKS = frozenset({b"tEXt", b"iTXt", b"zTXt", b"eXIf"})
JPEG_EXIF_MARKER = b"Exif\x00\x00"

CONTENT_PATTERNS = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    (
        "assigned secret",
        re.compile(
            r"(?i)\b(secret[_-]?key|api[_-]?key|token|password)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-/+]{32,}[\"']"
        ),
    ),
    (
        "email address",
        re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ),
    (
        "absolute host path",
        re.compile(
            r"(?:[A-Za-z]:\\Users\\|/Users/[A-Za-z]|/home/(?!developer\b)[A-Za-z]|/(?:root|srv|mnt)/)"
        ),
    ),
)


def is_violation(path: str) -> bool:
    candidate = PurePosixPath(path)
    if any(part in BAD_DIRECTORIES for part in candidate.parts):
        return True
    name = candidate.name.lower()
    if name.startswith(".env") and name != ".env.example":
        return True
    if ".db-" in name or ".sqlite-" in name or ".sqlite3-" in name:
        return True
    return name.endswith(BAD_SUFFIXES)


def find_violations(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if is_violation(path))


def png_metadata_chunks(data: bytes) -> list[str]:
    chunks = []
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type in PNG_METADATA_CHUNKS:
            chunks.append(chunk_type.decode("latin-1"))
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    return chunks


def content_violations(paths: Iterable[str]) -> list[str]:
    findings = []
    for path in paths:
        candidate = Path(path)
        name = candidate.name.lower()
        try:
            if name.endswith(".png"):
                data = candidate.read_bytes()
                if data.startswith(PNG_SIGNATURE):
                    for chunk in png_metadata_chunks(data):
                        findings.append(f"{path}: PNG {chunk} metadata chunk")
                continue
            if name.endswith((".jpg", ".jpeg")):
                if JPEG_EXIF_MARKER in candidate.read_bytes():
                    findings.append(f"{path}: JPEG Exif metadata")
                continue
            size = candidate.stat().st_size
            if size <= MAX_SCAN_BYTES:
                text = candidate.read_text(encoding="utf-8")
            else:
                with candidate.open("rb") as handle:
                    head = handle.read(MAX_SCAN_BYTES)
                    handle.seek(size - MAX_SCAN_BYTES)
                    tail = handle.read(MAX_SCAN_BYTES)
                text = (head + tail).decode("utf-8", errors="ignore")
        except OSError, UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            for label, pattern in CONTENT_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{path}:{line_number}: {label}")
    return findings


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [entry.decode() for entry in result.stdout.split(b"\0") if entry]


def local_files() -> list[str]:
    root = Path.cwd()
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    return [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not ignored.intersection(path.parts)
    ]


def candidate_files() -> list[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip() == b"true":
        return tracked_files()
    return local_files()


def main() -> int:
    files = candidate_files()
    violations = find_violations(files)
    findings = content_violations(files)
    if violations:
        print("Tracked private-data files found:")
        for path in violations:
            print(f"  {path}")
    if findings:
        print("Private data found in tracked file contents:")
        for finding in findings:
            print(f"  {finding}")
    if violations or findings:
        return 1
    print("Hygiene check passed: no private-data files or content are tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
