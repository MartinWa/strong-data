from datetime import date, datetime
from decimal import Decimal

import pytest

from parsing import (
    InvalidCSVError,
    classify_muscle,
    estimate_1rm,
    parse_duration,
    parse_rpe,
    parse_workouts,
    program_name,
)

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE"


def csv_text(*rows: str) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("54m", 54),
        ("1h 2m", 62),
        ("1h", 60),
        ("54", 54),
        ("", None),
        ("bogus", None),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("6", Decimal("6.0")),
        ("7.5", Decimal("7.5")),
        ("10", Decimal("10.0")),
        ("5.5", None),
        ("10.5", None),
        ("7.25", None),
        ("bad", None),
        ("", None),
    ],
)
def test_parse_rpe(value, expected):
    assert parse_rpe(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Bench Press (Barbell)", "Chest"),
        ("Lat Pulldown (Cable)", "Lats"),
        ("Deadlift (Barbell)", "Lower Back"),
        ("Bicep Curl (Dumbbell)", "Biceps"),
        ("Plank", "Core"),
        ("Mystery Movement", "Other"),
    ],
)
def test_classify_muscle(name, expected):
    assert classify_muscle(name) == expected


def test_program_name_and_estimate_1rm():
    assert program_name("Push Day #3") == "Push Day"
    assert program_name("Push Day") == "Push Day"
    assert estimate_1rm(Decimal("80"), 5) == Decimal("80") * (Decimal(1) + Decimal(5) / Decimal(30))
    assert estimate_1rm(None, 5) is None
    assert estimate_1rm(Decimal("0"), 5) is None
    assert estimate_1rm(Decimal("80"), 0) is None


def test_parse_workouts_builds_sessions_and_derived_fields():
    text = csv_text(
        "2026-01-05 09:00:00,Push Day #3,54m,Bench Press (Barbell),2,80,5,0,0,8.0",
        "2026-01-05 08:30:00,Push Day #3,54m,Bench Press (Barbell),1,80,5,0,0,7.5",
        "2026-01-05 08:35:00,Push Day #3,,Chest Fly,1,,,0,0,",
        "2026-01-06 07:00:00,Pull Day,1h 2m,Lat Pulldown (Cable),1,60,10,0,0,9.0",
    )
    result = parse_workouts(text)

    assert result.warnings == ()
    assert result.exercises == (
        "Bench Press (Barbell)",
        "Chest Fly",
        "Lat Pulldown (Cable)",
    )
    assert len(result.sessions) == 2

    first = result.sessions[0]
    assert first.session_date == date(2026, 1, 5)
    assert first.program == "Push Day"
    assert first.workout_name == "Push Day #3"
    assert first.start_time == datetime(2026, 1, 5, 8, 30)
    assert first.duration_min == 54
    assert first.set_count == 3
    assert first.total_volume_kg == Decimal("800")

    weighted = first.sets[0]
    assert weighted.set_order == 2
    assert weighted.weight_kg == Decimal("80")
    assert weighted.rpe == Decimal("8.0")
    assert weighted.volume_kg == Decimal("400")
    assert weighted.est_1rm_kg == Decimal("80") * (Decimal(1) + Decimal(5) / Decimal(30))

    bodyweight = first.sets[2]
    assert bodyweight.weight_kg is None
    assert bodyweight.rpe is None
    assert bodyweight.volume_kg == Decimal("0")
    assert bodyweight.est_1rm_kg is None


def test_invalid_rows_are_skipped_or_warned():
    text = csv_text(
        "not-a-date,Push Day,54m,Bench Press,1,80,5,0,0,8",
        "2026-01-05 08:00:00,Push Day,54m,Bench Press,oops,80,5,0,0,8",
        "2026-01-05 08:01:00,Push Day,54m,Bench Press,1,80,many,0,0,8",
        "2026-01-05 08:02:00,Push Day,54m,Bench Press,1,bad,5,0,0,5.25",
        "2026-01-05 08:03:00,Push Day,54m,Bench Press,1,80,5,0,0,",
    )
    result = parse_workouts(text)

    assert len(result.sessions) == 1
    assert result.sessions[0].set_count == 2
    assert len(result.warnings) == 5
    assert "row skipped" in result.warnings[0]
    assert "invalid RPE" in result.warnings[4]


def test_rejects_non_exports_and_strips_byte_order_mark():
    with pytest.raises(InvalidCSVError):
        parse_workouts("Date,Workout Name\n2026-01-01,A\n")
    with pytest.raises(InvalidCSVError):
        parse_workouts("")

    text = "\ufeff" + csv_text("2026-01-05 08:00:00,Push,54m,Bench,1,80,5,0,0,8")
    assert len(parse_workouts(text).sessions) == 1
