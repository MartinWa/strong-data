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
    assert summary["sample_sessions"][0]["sets"][0]["exercise_name"] == "Bench Press (Barbell)"


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

    assert summary["sample_set_count"] == pending.SAMPLE_SET_LIMIT
    assert summary["total_sets"] == 30
    assert summary["warning_total"] == 0
    assert summary["warning_groups"] == []


def test_summarize_caps_the_sample_across_sessions_and_keeps_the_partial_group():
    rows = []
    for day, name in (("05", "Push Day"), ("06", "Pull Day")):
        for minute in range(15):
            rows.append(
                f"2026-02-{day} 09:{minute:02d}:00,{name},54m,Exercise {minute:02d},1,80,5,0,0,8"
            )

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert summary["sample_set_count"] == pending.SAMPLE_SET_LIMIT
    assert [len(group["sets"]) for group in summary["sample_sessions"]] == [15, 5]
    assert [group["date"] for group in summary["sample_sessions"]] == [
        "2026-02-06",
        "2026-02-05",
    ]


def test_summarize_orders_sessions_newest_first_like_the_sessions_page():
    rows = [
        "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,80,5,0,0,8",
        "2026-02-10 18:00:00,Pull Day,47m,Barbell Row,1,60,8,0,0,8",
        "2026-01-05 19:00:00,Legs Day,40m,Back Squat,1,100,5,0,0,9",
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert [session["date"] for session in summary["sessions"]] == [
        "2026-02-10",
        "2026-01-05",
        "2026-01-05",
    ]
    assert [session["workout_name"] for session in summary["sessions"]][1:] == [
        "Push Day",
        "Legs Day",
    ]
    assert [group["workout_name"] for group in summary["sample_sessions"]] == [
        "Pull Day",
        "Push Day",
        "Legs Day",
    ]
    assert summary["sample_sessions"][0]["sets"][0]["exercise_name"] == "Barbell Row"
    assert summary["sample_sessions"][0]["date"] == "2026-02-10"
    assert summary["sample_set_count"] == 3


def test_summarize_groups_warnings_by_cause_with_counts():
    rows = [
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,{rpe}"
        for minute, rpe in enumerate(["8", "8", "99", "8", "2"])
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert summary["warning_total"] == 2
    assert [group["message"] for group in summary["warning_groups"]] == [
        "invalid RPE; stored as null"
    ]
    assert summary["warning_groups"][0]["count"] == 2
    assert summary["warning_groups"][0]["rows"] == [4, 6]
    assert summary["warning_groups"][0]["hidden_rows"] == 0


def test_summarize_counts_every_warning_but_caps_the_listed_lines():
    rows = [
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,99"
        for minute in range(30)
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))
    group = summary["warning_groups"][0]

    assert summary["warning_total"] == 30
    assert group["count"] == 30
    assert len(group["rows"]) == pending.WARNING_ROW_LIMIT
    assert group["rows"][0] == 2
    assert group["hidden_rows"] == 30 - pending.WARNING_ROW_LIMIT
