import contextlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from parsing import ParsedWorkouts

PENDING_TTL_SECONDS = 3600
SAMPLE_SET_LIMIT = 20
WARNING_LIMIT = 50
IMPORT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")


def pending_dir() -> Path:
    configured = os.environ.get("STRONG_PENDING_DIR")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "strong-data-pending"


def _ensure_dir() -> Path:
    base = pending_dir()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.suppress(OSError):
        base.chmod(0o700)
    return base


def _paths(import_id: str) -> tuple[Path, Path] | None:
    if not IMPORT_ID_PATTERN.fullmatch(import_id):
        return None
    base = pending_dir()
    return base / f"{import_id}.csv", base / f"{import_id}.json"


def save(import_id: str, raw: str, parsed: ParsedWorkouts) -> None:
    paths = _paths(import_id)
    if paths is None:
        raise ValueError("Invalid import id")
    csv_path, summary_path = paths
    _ensure_dir()
    csv_path.write_text(raw, encoding="utf-8")
    csv_path.chmod(0o600)
    summary_path.write_text(json.dumps(summarize(parsed)), encoding="utf-8")
    summary_path.chmod(0o600)


def load_summary(import_id: str) -> dict | None:
    paths = _paths(import_id)
    if paths is None:
        return None
    try:
        summary = json.loads(paths[1].read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return summary if isinstance(summary, dict) else None


def load_csv(import_id: str) -> str | None:
    paths = _paths(import_id)
    if paths is None:
        return None
    try:
        return paths[0].read_text(encoding="utf-8")
    except OSError:
        return None


def discard(import_id: str) -> None:
    paths = _paths(import_id)
    if paths is None:
        return
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def purge_stale(ttl_seconds: int = PENDING_TTL_SECONDS) -> None:
    try:
        entries = list(pending_dir().iterdir())
    except OSError:
        return
    cutoff = time.time() - ttl_seconds
    for path in entries:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def summarize(parsed: ParsedWorkouts) -> dict:
    sessions = [
        {
            "date": session.session_date.isoformat(),
            "workout_name": session.workout_name,
            "program": session.program,
            "set_count": session.set_count,
            "total_volume_kg": str(round(session.total_volume_kg, 2)),
            "duration_min": session.duration_min,
        }
        for session in parsed.sessions
    ]
    sample_sets = []
    for session in parsed.sessions:
        for item in session.sets:
            if len(sample_sets) >= SAMPLE_SET_LIMIT:
                break
            sample_sets.append(
                {
                    "set_time": item.set_time.isoformat(sep=" "),
                    "exercise_name": item.exercise_name,
                    "set_order": item.set_order,
                    "weight_kg": None if item.weight_kg is None else str(item.weight_kg),
                    "reps": item.reps,
                    "rpe": None if item.rpe is None else str(item.rpe),
                    "volume_kg": str(round(item.volume_kg, 2)),
                    "est_1rm_kg": (
                        None if item.est_1rm_kg is None else str(round(item.est_1rm_kg, 2))
                    ),
                }
            )
        if len(sample_sets) >= SAMPLE_SET_LIMIT:
            break
    warnings = list(parsed.warnings[:WARNING_LIMIT])
    return {
        "sessions": sessions,
        "exercises": list(parsed.exercises),
        "warnings": warnings,
        "hidden_warnings": len(parsed.warnings) - len(warnings),
        "sample_sets": sample_sets,
        "total_sets": sum(session.set_count for session in parsed.sessions),
    }
