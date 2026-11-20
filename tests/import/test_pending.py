import os
import threading
import time
from io import StringIO

import pytest
from django.core.management import call_command

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
    assert summary["sample_groups"][0]["exercise_name"] == "Bench Press (Barbell)"


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

    assert pending.purge_stale() == 2

    assert sorted(path.name for path in pending_root.iterdir()) == [
        f"{OTHER_ID}.csv",
        f"{OTHER_ID}.json",
    ]


def test_purge_stale_tolerates_a_missing_directory(pending_root):
    assert pending.purge_stale() == 0

    assert not pending_root.exists()


def test_start_sweeper_is_opt_in(pending_root):
    assert pending.start_sweeper(0) is None
    assert pending.start_sweeper(-1) is None
    assert not pending_root.exists()


def test_start_sweeper_purges_expired_files_on_a_timer(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))
    expired = time.time() - pending.PENDING_TTL_SECONDS - 60
    for suffix in ("csv", "json"):
        os.utime(pending_root / f"{IMPORT_ID}.{suffix}", (expired, expired))

    stop = threading.Event()
    thread = pending.start_sweeper(0.01, stop)

    try:
        assert thread is not None
        assert thread.daemon is True
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and list(pending_root.iterdir()):
            time.sleep(0.02)

        assert list(pending_root.iterdir()) == []
    finally:
        stop.set()
        thread.join(5)

    assert not thread.is_alive()


def test_sweep_survives_a_failing_purge(monkeypatch, caplog):
    calls = []

    def explode(ttl_seconds=pending.PENDING_TTL_SECONDS):
        calls.append(ttl_seconds)
        raise PermissionError("synthetic sweep failure")

    monkeypatch.setattr(pending, "purge_stale", explode)
    stop = threading.Event()
    stop.set()

    pending._sweep_forever(60, stop)

    assert calls == [pending.PENDING_TTL_SECONDS]
    assert "Staged upload sweep failed" in caplog.text


def test_purge_pending_command_removes_expired_files_and_reports_them(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))
    pending.save(OTHER_ID, SAMPLE, parse_workouts(SAMPLE))
    expired = time.time() - pending.PENDING_TTL_SECONDS - 60
    for suffix in ("csv", "json"):
        os.utime(pending_root / f"{IMPORT_ID}.{suffix}", (expired, expired))

    stdout = StringIO()
    call_command("purge_pending", stdout=stdout)

    assert stdout.getvalue().strip() == "Removed 2 stale pending files."
    assert sorted(path.name for path in pending_root.iterdir()) == [
        f"{OTHER_ID}.csv",
        f"{OTHER_ID}.json",
    ]


def test_purge_pending_command_honours_a_shorter_ttl(pending_root):
    pending.save(IMPORT_ID, SAMPLE, parse_workouts(SAMPLE))

    stdout = StringIO()
    call_command("purge_pending", "--ttl", "0", stdout=stdout)

    assert stdout.getvalue().strip() == "Removed 2 stale pending files."
    assert list(pending_root.iterdir()) == []


def test_purge_pending_command_reports_an_empty_directory(pending_root):
    stdout = StringIO()
    call_command("purge_pending", stdout=stdout)

    assert stdout.getvalue().strip() == "Removed 0 stale pending files."
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
    assert summary["warning_rows"] == 0
    assert summary["warning_groups"] == []


def test_summarize_caps_the_sample_across_sessions_and_keeps_the_partial_group():
    rows = []
    for day in ("05", "06"):
        for minute in range(15):
            rows.append(f"2026-02-{day} 09:{minute:02d}:00,Push Day,54m,Bench Press,1,80,5,0,0,8")

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert summary["sample_set_count"] == pending.SAMPLE_SET_LIMIT
    assert [group["set_count"] for group in summary["sample_groups"]] == [15, 5]
    assert [group["hidden_sets"] for group in summary["sample_groups"]] == [0, 10]
    assert [group["session_date"] for group in summary["sample_groups"]] == [
        "2026-02-06",
        "2026-02-05",
    ]


def test_summarize_groups_the_sample_by_exercise_in_first_seen_order():
    rows = [
        "2026-01-05 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8",
        "2026-01-05 09:05:00,Push Day,54m,Incline Press,1,60,8,0,0,8",
        "2026-01-05 09:10:00,Push Day,54m,Bench Press,2,80,5,0,0,8",
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert [group["exercise_name"] for group in summary["sample_groups"]] == [
        "Bench Press",
        "Incline Press",
    ]
    assert [group["set_count"] for group in summary["sample_groups"]] == [2, 1]
    assert [item["set_order"] for item in summary["sample_groups"][0]["sets"]] == [1, 2]
    assert [group["starts_session"] for group in summary["sample_groups"]] == [True, False]


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
    assert [group["exercise_name"] for group in summary["sample_groups"]] == [
        "Barbell Row",
        "Bench Press (Barbell)",
        "Back Squat",
    ]
    assert [group["session_date"] for group in summary["sample_groups"]] == [
        "2026-02-10",
        "2026-01-05",
        "2026-01-05",
    ]
    assert [group["starts_session"] for group in summary["sample_groups"]] == [
        True,
        True,
        True,
    ]
    assert summary["sample_set_count"] == 3


def test_summarize_groups_warnings_by_cause_with_counts():
    rows = [
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,{rpe}"
        for minute, rpe in enumerate(["8", "8", "99", "8", "2"])
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert summary["warning_total"] == 2
    assert summary["warning_rows"] == 2
    assert [group["message"] for group in summary["warning_groups"]] == [
        "invalid RPE; stored as null"
    ]
    assert summary["warning_groups"][0]["count"] == 2
    assert summary["warning_groups"][0]["rows"] == [4, 6]
    assert summary["warning_groups"][0]["hidden_rows"] == 0


def test_summarize_counts_affected_rows_separately_from_warning_messages():
    rows = ["2026-01-05 09:00:00,Push Day,54m,Bench Press,1,abc,5,0,0,99"]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))

    assert summary["warning_total"] == 2
    assert summary["warning_rows"] == 1
    assert [group["message"] for group in summary["warning_groups"]] == [
        "invalid RPE; stored as null",
        "invalid weight; stored as null",
    ]
    assert [group["count"] for group in summary["warning_groups"]] == [1, 1]


def test_summarize_counts_every_warning_but_caps_the_listed_lines():
    rows = [
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,99"
        for minute in range(30)
    ]

    summary = pending.summarize(parse_workouts(csv_text(*rows)))
    group = summary["warning_groups"][0]

    assert summary["warning_total"] == 30
    assert summary["warning_rows"] == 30
    assert group["count"] == 30
    assert len(group["rows"]) == pending.WARNING_ROW_LIMIT
    assert group["rows"][0] == 2
    assert group["hidden_rows"] == 30 - pending.WARNING_ROW_LIMIT
