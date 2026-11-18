"""Pure, deterministic parsing of Strong app CSV exports."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
REQUIRED_HEADERS = frozenset(
    {"Date", "Workout Name", "Exercise Name", "Set Order", "Weight", "Reps"}
)
PROGRAM_SUFFIX = re.compile(r"\s+#\d+$")
DURATION_PATTERNS = (
    (r"(\d+)\s*h\s*(\d+)\s*m", 60, 1),
    (r"(\d+)\s*m", 1, None),
    (r"(\d+)\s*h", 60, None),
    (r"(\d+)", 1, None),
)
MUSCLE_GUESS = (
    (("bench", "chest fly", "chest press", "push up", "pec"), "Chest"),
    (("lat pulldown", "pull up", "chin up"), "Lats"),
    (
        ("seated row", "cable row", "bent over row", "incline row", "t-bar row"),
        "Upper Back",
    ),
    (("deadlift", "back extension", "good morning"), "Lower Back"),
    (
        (
            "overhead press",
            "shoulder press",
            "lateral raise",
            "front raise",
            "arnold press",
            "rotor cuff",
            "shrug",
            "face pull",
            "reverse fly",
            "rear delt",
        ),
        "Shoulders",
    ),
    (("leg curl", "romanian deadlift", "rdl", "nordic curl"), "Hamstrings"),
    (("curl", "preacher", "hammer"), "Biceps"),
    (
        (
            "triceps",
            "skullcrusher",
            "pushdown",
            "dip",
            "stång över huvudet",
            "stang over huvudet",
        ),
        "Triceps",
    ),
    (("squat", "leg press", "leg extension", "lunge", "hack squat"), "Quads"),
    (
        ("hip thrust", "hip abductor", "hip adductor", "glute", "airplane", "abductor"),
        "Glutes",
    ),
    (("calf raise", "calf"), "Calves"),
    (
        (
            "plank",
            "crunch",
            "sit up",
            "leg raise",
            "side bend",
            "ab wheel",
            "russian twist",
            "hanging knee",
        ),
        "Core",
    ),
)


class InvalidCSVError(ValueError):
    """Raised when the input is not a Strong CSV export."""


@dataclass(frozen=True)
class SetRow:
    set_time: datetime
    exercise_name: str
    set_order: int
    weight_kg: Decimal | None
    reps: int
    rpe: Decimal | None
    distance: Decimal | None
    seconds: Decimal | None
    volume_kg: Decimal
    est_1rm_kg: Decimal | None


@dataclass(frozen=True)
class Session:
    session_date: date
    program: str
    workout_name: str
    start_time: datetime
    duration_min: int | None
    set_count: int
    total_volume_kg: Decimal
    sets: tuple[SetRow, ...]


@dataclass(frozen=True)
class ParsedWorkouts:
    sessions: tuple[Session, ...]
    exercises: tuple[str, ...]
    warnings: tuple[str, ...]


def parse_duration(value: str | None) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    for pattern, hours_multiplier, minutes_multiplier in DURATION_PATTERNS:
        match = re.fullmatch(pattern, text)
        if match:
            parts = [int(part) for part in match.groups()]
            total = parts[0] * hours_multiplier
            if minutes_multiplier is not None:
                total += parts[1] * minutes_multiplier
            return total
    return None


def to_decimal(value: str | None) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_int(value: str | None, default: int | None = None) -> int | None:
    text = (value or "").strip()
    if not text:
        return default
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return int(number)


def parse_datetime(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_rpe(value: str | None) -> Decimal | None:
    number = to_decimal(value)
    if number is None:
        return None
    if not Decimal("6.0") <= number <= Decimal("10.0"):
        return None
    doubled = number * 2
    if doubled != doubled.to_integral_value():
        return None
    return number


def program_name(workout_name: str) -> str:
    return PROGRAM_SUFFIX.sub("", workout_name).strip()


def classify_muscle(name: str | None) -> str:
    lowered = (name or "").lower()
    for keywords, muscle in MUSCLE_GUESS:
        if any(keyword in lowered for keyword in keywords):
            return muscle
    return "Other"


def estimate_1rm(weight: Decimal | None, reps: int) -> Decimal | None:
    if weight is None or weight <= 0 or reps <= 0:
        return None
    return weight * (Decimal(1) + Decimal(reps) / Decimal(30))


def parse_workouts(text: str) -> ParsedWorkouts:
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise InvalidCSVError("CSV file is empty")

    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED_HEADERS - set(reader.fieldnames or ())
    if missing:
        raise InvalidCSVError("Missing required CSV headers: " + ", ".join(sorted(missing)))

    sessions: dict[tuple[str, str], dict] = {}
    exercises: set[str] = set()
    warnings: list[str] = []

    for row in reader:
        line = reader.line_num
        set_time = parse_datetime(row.get("Date"))
        if set_time is None:
            warnings.append(f"Row {line}: invalid date; row skipped")
            continue

        workout_name = (row.get("Workout Name") or "").strip() or "Workout"
        exercise_name = (row.get("Exercise Name") or "").strip() or "Unknown"
        set_order = parse_int(row.get("Set Order"), default=1)
        if set_order is None or set_order < 1:
            warnings.append(f"Row {line}: invalid set order; row skipped")
            continue
        reps = parse_int(row.get("Reps"), default=0)
        if reps is None or reps < 0:
            warnings.append(f"Row {line}: invalid reps; row skipped")
            continue

        weight = to_decimal(row.get("Weight"))
        if weight is not None and weight < 0:
            warnings.append(f"Row {line}: negative weight; row skipped")
            continue
        if weight is None and (row.get("Weight") or "").strip():
            warnings.append(f"Row {line}: invalid weight; stored as null")
        distance = to_decimal(row.get("Distance"))
        if distance is not None and distance < 0:
            warnings.append(f"Row {line}: negative distance; stored as null")
            distance = None
        seconds = to_decimal(row.get("Seconds"))
        if seconds is not None and seconds < 0:
            warnings.append(f"Row {line}: negative seconds; stored as null")
            seconds = None
        raw_rpe = (row.get("RPE") or "").strip()
        rpe = parse_rpe(raw_rpe)
        if raw_rpe and rpe is None:
            warnings.append(f"Row {line}: invalid RPE; stored as null")

        volume = (weight if weight is not None else Decimal(0)) * reps
        set_row = SetRow(
            set_time=set_time,
            exercise_name=exercise_name,
            set_order=set_order,
            weight_kg=weight,
            reps=reps,
            rpe=rpe,
            distance=distance,
            seconds=seconds,
            volume_kg=volume,
            est_1rm_kg=estimate_1rm(weight, reps),
        )

        key = (set_time.date().isoformat(), workout_name)
        session = sessions.get(key)
        if session is None:
            session = {
                "date": set_time.date(),
                "workout_name": workout_name,
                "duration_min": parse_duration(row.get("Duration")),
                "sets": [],
            }
            sessions[key] = session
        session["sets"].append(set_row)
        exercises.add(exercise_name)

    built_sessions = []
    for key in sorted(sessions):
        session = sessions[key]
        sets = tuple(session["sets"])
        built_sessions.append(
            Session(
                session_date=session["date"],
                program=program_name(session["workout_name"]),
                workout_name=session["workout_name"],
                start_time=min(item.set_time for item in sets),
                duration_min=session["duration_min"],
                set_count=len(sets),
                total_volume_kg=sum((item.volume_kg for item in sets), Decimal(0)),
                sets=sets,
            )
        )

    return ParsedWorkouts(
        sessions=tuple(built_sessions),
        exercises=tuple(sorted(exercises)),
        warnings=tuple(warnings),
    )
