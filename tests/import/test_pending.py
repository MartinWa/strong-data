import os
import time

import pytest

from parsing import parse_workouts
from workouts import pending

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE"
IMPORT_ID = "abcdefghijklmnop"
OTHER_ID = "qrstuvwxyz012345"


def csv_text(*rows: str) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"


SAMPLE = csv_text(
    "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,80,5,0,0,8.0",
    "2026-01-05 09:05:00,Push Day,54m,Chest Fly,1,,,0,0,",
)


@pytest.fixture(autouse=True)
def pending_root(tmp_path, monkeypatch):
    root = tmp_path / "pending"
    monkeypatch.setenv("STRONG_PENDING_DIR", str(root))
    return root


def test_save_round_trips_the_csv_and_summary(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))

    summary = pending.load_summary(IMPORT_ID)

    assert pending.load_csv(IMPORT_ID) == SAMPLE
    assert summary["total_sets"] == 2
    assert summary["sessions"][0]["workout_name"] == "Push Day"
    assert summary["sample_sets"][0]["exercise_name"] == "Bench Press (Barbell)"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_saved_files_and_directory_are_private(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))

    assert pending_root.stat().st_mode & 0o777 == 0o700
    assert (pending_root / f"{IMPORT_ID}.csv").stat().st_mode & 0o777 == 0o600
    assert (pending_root / f"{IMPORT_ID}.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "import_id",
    ["../../etc/passwd", "abc/def", "a" * 15, "a" * 65, "", "id with space", "id.with.dot"],
)
def test_invalid_ids_are_rejected(import_id):
    with pytest.raises(ValueError):
        pending.save(import_id, SAMPLE, parse_workouts(SAMPLE))

    assert pending.load_summary(import_id) is None
    assert pending.load_csv(import_id) is None
    pending.discard(import_id)


def test_missing_files_load_as_none(pending_root):
    assert pending.load_summary(IMPORT_ID) is None
    assert pending.load_csv(IMPORT_ID) is None


def test_corrupt_summary_loads_as_none(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))
    (pending_root / f"{IMPORT_ID}.json").write_text("{not json", encoding="utf-8")

    assert pending.load_summary(IMPORT_ID) is None


def test_non_object_summary_loads_as_none(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))
    (pending_root / f"{IMPORT_ID}.json").write_text("5", encoding="utf-8")

    assert pending.load_summary(IMPORT_ID) is None


def test_discard_removes_both_files(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))

    pending.discard(IMPORT_ID)

    assert list(pending_root.iterdir()) == []


def test_purge_stale_removes_only_expired_files(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))
    pending.save(OTHER_ID, SAMPLE, parse_workouts(SAMPLE))
    expired = time.time() - pending.PENDING_TTL_SECONDS - 60
    for suffix in ("csv", "json"):
        os.utime(pending_root / f"{IMPORT_ID}.{suffix}", (expired, expired))

    pending.purge_stale()

    assert sorted(path.name for path in pending_root.iterdir()) == [
        f"{OTHER_ID}.csv",
        f"{OTHER_ID}.json",
    ]


def test_purge_stale_tolerates_a_missing_directory(pending_root):
    pending.purge_stale()

    assert not pending_root.exists()


def test_summarize_caps_the_sample_and_reports_the_total():
    rows = [
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,"
        for minute in range(30)
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert len(summary["sample_sets"]) == pending.SAMPLE_SET_LIMIT
    assert summary["total_sets"] == 30
    assert summary["hidden_warnings"] == 0
