"""Fail when a private-data file is tracked by git."""

from __future__ import annotations

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


def is_violation(path: str) -> bool:
    candidate = PurePosixPath(path)
    if any(part in BAD_DIRECTORIES for part in candidate.parts):
        return True
    name = candidate.name.lower()
    if name.startswith(".env") and name != ".env.example":
        return True
    if ".db-" in name or ".sqlite-" in name:
        return True
    return name.endswith(BAD_SUFFIXES)


def find_violations(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if is_violation(path))


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
    violations = find_violations(candidate_files())
    if violations:
        print("Tracked private-data files found:")
        for path in violations:
            print(f"  {path}")
        return 1
    print("Hygiene check passed: no private-data files are tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
