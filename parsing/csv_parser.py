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
MAX_TEXT_LENGTH = 255
MAX_INT_VALUE = 2_147_483_647
MAX_IMPORT_ROWS = 100_000
FIELD_DIGITS = {
    "weight": (8, 2),
    "distance": (8, 2),
    "seconds": (8, 2),
    "est_1rm": (8, 2),
    "volume": (12, 2),
    "total_volume": (12, 2),
}
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
            "rotator cuff",
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
        ),
        "Triceps",
    ),
    (("squat", "leg press", "leg extension", "lunge", "hack squat"), "Quads"),
    (
        ("hip thrust", "hip abductor", "hip adductor", "glute", "airplane", "abductor"),
        "Glutes",
    ),
    (("calf raise", "calf"), "Calves"),
    (("crunch", "sit up", "sit-up", "leg raise"), "Abs"),
    (("plank", "ab wheel", "hanging knee", "russian twist", "side bend"), "Core"),
)


class InvalidCSVError(ValueError):
    """Raised when the input is not a Strong CSV export."""


def _read_rows(reader: csv.DictReader):
    try:
        yield from reader
    except csv.Error as exc:
        raise InvalidCSVError(f"Invalid CSV: {exc}") from exc


def fits_decimal(value: Decimal | None, field: str) -> bool:
    max_digits, decimal_places = FIELD_DIGITS[field]
    if value is None:
        return True
    try:
        quantized = value.quantize(Decimal(1).scaleb(-decimal_places))
    except InvalidOperation:
        return False
    digits = quantized.as_tuple()
    integer_digits = max(0, len(digits.digits) + digits.exponent)
    return integer_digits <= max_digits - decimal_places


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
    if not number.is_finite() or number != number.to_integral_value():
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
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise InvalidCSVError(f"Invalid CSV: {exc}") from exc
    missing = REQUIRED_HEADERS - set(fieldnames or ())
    if missing:
        raise InvalidCSVError("Missing required CSV headers: " + ", ".join(sorted(missing)))

    sessions: dict[tuple[str, str], dict] = {}
    exercises: set[str] = set()
    warnings: list[str] = []

    row_count = 0
    for row in _read_rows(reader):
        row_count += 1
        if row_count > MAX_IMPORT_ROWS:
            raise InvalidCSVError(f"CSV export exceeds the {MAX_IMPORT_ROWS:,}-row limit")
        line = reader.line_num
        if any(row.get(header) is None for header in REQUIRED_HEADERS):
            warnings.append(f"Row {line}: incomplete row; row skipped")
            continue
        set_time = parse_datetime(row.get("Date"))
        if set_time is None:
            warnings.append(f"Row {line}: invalid date; row skipped")
            continue

        raw_workout_name = (row.get("Workout Name") or "").strip()
        raw_exercise_name = (row.get("Exercise Name") or "").strip()
        if not raw_workout_name and not raw_exercise_name:
            warnings.append(f"Row {line}: missing workout and exercise; row skipped")
            continue
        workout_name = raw_workout_name or "Workout"
        exercise_name = raw_exercise_name or "Unknown"
        if max(len(workout_name), len(exercise_name)) > MAX_TEXT_LENGTH:
            warnings.append(f"Row {line}: name too long; row skipped")
            continue
        set_order = parse_int(row.get("Set Order"), default=1)
        if set_order is None or not 1 <= set_order <= MAX_INT_VALUE:
            warnings.append(f"Row {line}: invalid set order; row skipped")
            continue
        reps = parse_int(row.get("Reps"), default=0)
        if reps is None or not 0 <= reps <= MAX_INT_VALUE:
            warnings.append(f"Row {line}: invalid reps; row skipped")
            continue
        duration_min = parse_duration(row.get("Duration"))
        if duration_min is not None and duration_min > MAX_INT_VALUE:
            warnings.append(f"Row {line}: invalid duration; stored as null")
            duration_min = None

        raw_weight = (row.get("Weight") or "").strip()
        weight = to_decimal(raw_weight)
        if weight is not None and weight < 0:
            warnings.append(f"Row {line}: negative weight; row skipped")
            continue
        if weight is not None and not fits_decimal(weight, "weight"):
            warnings.append(f"Row {line}: weight out of range; stored as null")
            weight = None
        elif weight is None and raw_weight:
            warnings.append(f"Row {line}: invalid weight; stored as null")
        if weight == 0:
            weight = None
        raw_distance = (row.get("Distance") or "").strip()
        distance = to_decimal(raw_distance)
        if distance is not None and distance < 0:
            warnings.append(f"Row {line}: negative distance; stored as null")
            distance = None
        elif distance is not None and not fits_decimal(distance, "distance"):
            warnings.append(f"Row {line}: distance out of range; stored as null")
            distance = None
        elif distance is None and raw_distance:
            warnings.append(f"Row {line}: invalid distance; stored as null")
        raw_seconds = (row.get("Seconds") or "").strip()
        seconds = to_decimal(raw_seconds)
        if seconds is not None and seconds < 0:
            warnings.append(f"Row {line}: negative seconds; stored as null")
            seconds = None
        elif seconds is not None and not fits_decimal(seconds, "seconds"):
            warnings.append(f"Row {line}: seconds out of range; stored as null")
            seconds = None
        elif seconds is None and raw_seconds:
            warnings.append(f"Row {line}: invalid seconds; stored as null")
        raw_rpe = (row.get("RPE") or "").strip()
        rpe = parse_rpe(raw_rpe)
        if raw_rpe and rpe is None:
            warnings.append(f"Row {line}: invalid RPE; stored as null")

        volume = (weight if weight is not None else Decimal(0)) * reps
        if not fits_decimal(volume, "volume"):
            warnings.append(f"Row {line}: volume out of range; row skipped")
            continue
        est_1rm = estimate_1rm(weight, reps)
        if est_1rm is not None and not fits_decimal(est_1rm, "est_1rm"):
            warnings.append(f"Row {line}: estimated 1RM out of range; stored as null")
            est_1rm = None

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
            est_1rm_kg=est_1rm,
        )

        key = (set_time.date().isoformat(), workout_name)
        session = sessions.get(key)
        running_total = session["total"] if session else Decimal(0)
        if not fits_decimal(running_total + volume, "total_volume"):
            warnings.append(f"Row {line}: session volume out of range; row skipped")
            continue
        if session is None:
            session = {
                "date": set_time.date(),
                "workout_name": workout_name,
                "duration_min": duration_min,
                "sets": [],
                "total": Decimal(0),
            }
            sessions[key] = session
        elif session["duration_min"] is None and duration_min is not None:
            session["duration_min"] = duration_min
        session["total"] += volume
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
