import contextlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from parsing import ParsedWorkouts

from .limits import MAX_UPLOAD_BYTES

PENDING_TTL_SECONDS = 3600
UNDO_TTL_SECONDS = int(os.environ.get("STRONG_UNDO_TTL_SECONDS", "86400"))
STASH_MAX_BYTES = MAX_UPLOAD_BYTES
SAMPLE_SET_LIMIT = 20
WARNING_ROW_LIMIT = 20
PREVIEW_SESSION_LIMIT = 200
IMPORT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")
ROW_WARNING_PATTERN = re.compile(r"Row (\d+): (.+)")


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


def undo_dir() -> Path:
    return pending_dir() / "undo"


def _stash_path(stash_id: str) -> Path | None:
    if not IMPORT_ID_PATTERN.fullmatch(stash_id):
        return None
    return undo_dir() / f"{stash_id}.json"


def save_stash(stash_id: str, payload: dict) -> bool:
    path = _stash_path(stash_id)
    if path is None:
        return False
    raw = json.dumps(payload)
    if len(raw.encode("utf-8")) > STASH_MAX_BYTES:
        return False
    try:
        undo_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(raw, encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        return False
    return True


def _live_stash_path(stash_id: str) -> Path | None:
    path = _stash_path(stash_id)
    if path is None:
        return None
    try:
        if path.stat().st_mtime >= time.time() - UNDO_TTL_SECONDS:
            return path
    except OSError:
        return None
    return None


def stash_available(stash_id: str) -> bool:
    return _live_stash_path(stash_id) is not None


def load_stash(stash_id: str) -> dict | None:
    path = _live_stash_path(stash_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return data if isinstance(data, dict) else None


def discard_stash(stash_id: str) -> None:
    path = _stash_path(stash_id)
    if path is None:
        return
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def purge_stale(
    ttl_seconds: int = PENDING_TTL_SECONDS, undo_ttl_seconds: int = UNDO_TTL_SECONDS
) -> int:
    try:
        entries = list(pending_dir().iterdir())
    except OSError:
        return 0
    removed = _purge_files(entries, time.time() - ttl_seconds)
    try:
        undo_entries = list(undo_dir().iterdir())
    except OSError:
        return removed
    return removed + _purge_files(undo_entries, time.time() - undo_ttl_seconds)


def _purge_files(entries, cutoff: float) -> int:
    removed = 0
    for path in entries:
        if path.is_dir():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def start_sweeper(
    interval_seconds: int, stop: threading.Event | None = None
) -> threading.Thread | None:
    if interval_seconds <= 0:
        return None
    thread = threading.Thread(
        target=_sweep_forever,
        args=(interval_seconds, stop or threading.Event()),
        name="pending-sweeper",
        daemon=True,
    )
    thread.start()
    return thread


def _sweep_forever(interval_seconds: int, stop: threading.Event) -> None:
    logger = logging.getLogger(__name__)
    while True:
        try:
            purge_stale()
        except Exception:
            logger.exception("Staged upload sweep failed")
        if stop.wait(interval_seconds):
            return


def group_warnings(warnings: tuple[str, ...] | list[str]) -> list[dict]:
    groups: dict[str, dict] = {}
    for warning in warnings:
        match = ROW_WARNING_PATTERN.fullmatch(warning)
        message = match.group(2) if match else warning
        group = groups.setdefault(
            message,
            {"message": message, "count": 0, "rows": [], "hidden_rows": 0},
        )
        group["count"] += 1
        if match is None:
            continue
        if len(group["rows"]) < WARNING_ROW_LIMIT:
            group["rows"].append(int(match.group(1)))
        else:
            group["hidden_rows"] += 1
    return sorted(groups.values(), key=lambda group: (-group["count"], group["message"]))


def count_warning_rows(warnings: tuple[str, ...] | list[str]) -> int:
    lines: set[int] = set()
    unattributed = 0
    for warning in warnings:
        match = ROW_WARNING_PATTERN.fullmatch(warning)
        if match is None:
            unattributed += 1
        else:
            lines.add(int(match.group(1)))
    return len(lines) + unattributed


def summarize(parsed: ParsedWorkouts) -> dict:
    ordered_sessions = sorted(
        parsed.sessions,
        key=lambda session: (-session.session_date.toordinal(), session.workout_name),
    )
    sessions = [
        {
            "date": session.session_date.isoformat(),
            "workout_name": session.workout_name,
            "program": session.program,
            "set_count": session.set_count,
            "total_volume_kg": str(round(session.total_volume_kg, 2)),
            "duration_min": session.duration_min,
        }
        for session in ordered_sessions[:PREVIEW_SESSION_LIMIT]
    ]
    sample_groups = []
    sample_set_count = 0
    for session in ordered_sessions:
        if sample_set_count >= SAMPLE_SET_LIMIT:
            break
        totals: dict[str, int] = {}
        for item in session.sets:
            totals[item.exercise_name] = totals.get(item.exercise_name, 0) + 1
        buckets: dict[str, list[dict]] = {}
        for item in session.sets:
            if sample_set_count >= SAMPLE_SET_LIMIT:
                break
            buckets.setdefault(item.exercise_name, []).append(
                {
                    "set_time": item.set_time.isoformat(sep=" "),
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
            sample_set_count += 1
        for position, (exercise_name, sets) in enumerate(buckets.items()):
            sample_groups.append(
                {
                    "session_date": session.session_date.isoformat(),
                    "workout_name": session.workout_name,
                    "starts_session": position == 0,
                    "exercise_name": exercise_name,
                    "set_count": len(sets),
                    "hidden_sets": totals[exercise_name] - len(sets),
                    "sets": sets,
                }
            )
    warnings = list(parsed.warnings)
    return {
        "sessions": sessions,
        "session_total": len(parsed.sessions),
        "exercises": list(parsed.exercises),
        "warning_total": len(warnings),
        "warning_rows": count_warning_rows(warnings),
        "warning_groups": group_warnings(warnings),
        "sample_groups": sample_groups,
        "sample_set_count": sample_set_count,
        "total_sets": sum(session.set_count for session in parsed.sessions),
    }
