from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from parsing import ParsedWorkouts, classify_muscle, parse_workouts
from parsing.csv_parser import fits_decimal

from .models import Exercise, ExerciseMeta, WorkoutSession, WorkoutSet


class EmptyImportError(ValueError):
    """Raised when an export contains no importable sets."""


class ImportLimitError(ValueError):
    """Raised when a merge would exceed a storable field limit."""


@dataclass(frozen=True)
class ImportResult:
    added_sessions: int
    skipped_sessions: int
    added_sets: int
    skipped_sets: int
    conflicted: int
    exercises: int


KEY_CHUNK = 500
VALUE_FIELDS = ("weight_kg", "reps", "rpe", "distance", "seconds")
VALUE_PRECISION = {
    "weight_kg": Decimal("0.01"),
    "reps": None,
    "rpe": Decimal("0.1"),
    "distance": Decimal("0.01"),
    "seconds": Decimal("0.01"),
}
FIELD_LABELS = {
    "weight_kg": "weight",
    "reps": "reps",
    "rpe": "rpe",
    "distance": "distance",
    "seconds": "seconds",
}
CONFLICT_SAMPLE_LIMIT = 20


def _chunked(items, size=KEY_CHUNK):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _norm_value(field, value):
    if value is None:
        return None
    if field == "reps":
        return int(value)
    return value.quantize(VALUE_PRECISION[field])


def _norm_values(values):
    return tuple(
        _norm_value(field, value) for field, value in zip(VALUE_FIELDS, values, strict=True)
    )


def _utc(dt):
    if not timezone.is_aware(dt):
        dt = timezone.make_aware(dt, timezone.get_default_timezone())
    return dt.astimezone(UTC)


def _file_set_time(item, zone):
    return _utc(timezone.make_aware(item.set_time, zone))


def _stored_sessions(user, pairs):
    stored = {}
    for chunk in _chunked(pairs):
        query = Q()
        for session_date, workout_name in chunk:
            query |= Q(session_date=session_date, workout_name=workout_name)
        rows = (
            WorkoutSession.objects.filter(owner=user)
            .filter(query)
            .values_list("id", "session_date", "workout_name", "start_time", "duration_min")
        )
        for pk, session_date, workout_name, start_time, duration_min in rows:
            stored[(session_date, workout_name)] = {
                "id": pk,
                "start_time": start_time,
                "duration_min": duration_min,
            }
    return stored


def _stored_sets(session_ids):
    stored = {}
    by_time = {}
    for chunk in _chunked(session_ids):
        rows = WorkoutSet.objects.filter(session_id__in=chunk).values_list(
            "session_id", "exercise_id", "set_order", "set_time", *VALUE_FIELDS
        )
        for row in rows:
            set_time = _utc(row[3])
            key = (row[0], row[1], row[2], set_time)
            values = _norm_values(row[4:])
            stored[key] = values
            by_time.setdefault((row[0], row[1], set_time), {})[values] = row[2]
    return stored, by_time


def _session_id(ref):
    return ref["id"] if isinstance(ref, dict) else ref.id


def _classify(file_sessions, session_refs, exercises, stored, by_time, zone):
    """Decide per file set: "skip" (stored or exact duplicate), "conflict"
    (stored key, different values) or "add" (with a collision-free set_order).
    """
    decisions = []
    state_by_time = {}
    for _session, sets, key in file_sessions:
        session_id = _session_id(session_refs[key])
        for item in sets:
            exercise = exercises[item.exercise_name]
            set_time = _file_set_time(item, zone)
            tkey = (session_id, exercise.id, set_time)
            values = _norm_values(
                (item.weight_kg, item.reps, item.rpe, item.distance, item.seconds)
            )
            state = state_by_time.setdefault(tkey, {"orders": set(), "values": {}})
            if tkey in by_time:
                state["values"].update(by_time[tkey])
                state["orders"].update(by_time[tkey].values())
            if values in state["values"]:
                decisions.append((key, item, item.set_order, "skip", values))
                continue
            order = item.set_order
            if (session_id, exercise.id, order, set_time) in stored:
                decisions.append((key, item, order, "conflict", values))
                continue
            if order in state["orders"]:
                order = max(state["orders"]) + 1
            state["orders"].add(order)
            state["values"][values] = order
            decisions.append((key, item, order, "add", values))
    return decisions


def _merge_once(user, parsed: ParsedWorkouts) -> ImportResult:
    zone = timezone.get_default_timezone()
    with transaction.atomic():
        exercises = {}
        for name in parsed.exercises:
            exercise, _ = Exercise.objects.get_or_create(owner=user, name=name)
            exercises[name] = exercise
            ExerciseMeta.objects.get_or_create(
                owner=user,
                exercise_name=name,
                defaults={"muscle_group": classify_muscle(name)},
            )

        file_sessions = [
            (session, session.sets, (session.session_date, session.workout_name))
            for session in parsed.sessions
        ]
        pairs = sorted({key for _session, _sets, key in file_sessions})
        stored = _stored_sessions(user, pairs)

        pending = []
        session_refs = {}
        for session, sets, key in file_sessions:
            if key in stored:
                session_refs[key] = stored[key]
            else:
                pending.append((session, sets, key))

        created = WorkoutSession.objects.bulk_create(
            WorkoutSession(
                owner=user,
                session_date=session.session_date,
                program=session.program,
                workout_name=session.workout_name,
                start_time=timezone.make_aware(session.start_time, zone),
                duration_min=session.duration_min,
                set_count=len(sets),
                total_volume_kg=sum((item.volume_kg for item in sets), Decimal(0)),
            )
            for session, sets, key in pending
        )
        for (_session, _sets, key), row in zip(pending, created, strict=True):
            session_refs[key] = row

        stored_sets, by_time = _stored_sets([_session_id(ref) for ref in session_refs.values()])
        decisions = _classify(file_sessions, session_refs, exercises, stored_sets, by_time, zone)

        added_sets = 0
        skipped_sets = 0
        conflicted = 0
        set_rows = []
        for key, item, order, decision, _values in decisions:
            if decision == "skip":
                skipped_sets += 1
                continue
            if decision == "conflict":
                skipped_sets += 1
                conflicted += 1
                continue
            added_sets += 1
            set_rows.append(
                WorkoutSet(
                    owner=user,
                    session_id=_session_id(session_refs[key]),
                    exercise=exercises[item.exercise_name],
                    set_order=order,
                    weight_kg=item.weight_kg,
                    reps=item.reps,
                    rpe=item.rpe,
                    distance=item.distance,
                    seconds=item.seconds,
                    set_time=timezone.make_aware(item.set_time, zone),
                    volume_kg=item.volume_kg,
                    est_1rm_kg=item.est_1rm_kg,
                )
            )
        WorkoutSet.objects.bulk_create(set_rows)

        id_to_ref = {_session_id(ref): ref for ref in session_refs.values()}
        for chunk in _chunked(id_to_ref):
            rows = (
                WorkoutSet.objects.filter(session_id__in=chunk)
                .values("session_id")
                .annotate(count=Count("id"), volume=Sum("volume_kg"), first=Min("set_time"))
            )
            for row in rows:
                volume = row["volume"] or Decimal(0)
                if not fits_decimal(volume, "total_volume"):
                    raise ImportLimitError(
                        "A merged session would exceed the storable volume limit."
                    )
                ref = id_to_ref[row["session_id"]]
                start = ref["start_time"] if isinstance(ref, dict) else ref.start_time
                WorkoutSession.objects.filter(id=row["session_id"]).update(
                    set_count=row["count"],
                    total_volume_kg=volume,
                    start_time=min(_utc(start), _utc(row["first"])),
                )
        for session, _sets, key in file_sessions:
            ref = session_refs[key]
            if (
                isinstance(ref, dict)
                and ref["duration_min"] is None
                and session.duration_min is not None
            ):
                WorkoutSession.objects.filter(id=ref["id"]).update(
                    duration_min=session.duration_min
                )

    return ImportResult(
        added_sessions=len(created),
        skipped_sessions=len(file_sessions) - len(created),
        added_sets=added_sets,
        skipped_sets=skipped_sets,
        conflicted=conflicted,
        exercises=len(exercises),
    )


def import_workouts(user, parsed: ParsedWorkouts) -> ImportResult:
    if not parsed.sessions:
        raise EmptyImportError("CSV export contains no importable sets")
    try:
        return _merge_once(user, parsed)
    except IntegrityError:
        return _merge_once(user, parsed)


def import_workouts_csv(user, text: str) -> ImportResult:
    return import_workouts(user, parse_workouts(text))


def compare_import(user, parsed: ParsedWorkouts) -> dict:
    zone = timezone.get_default_timezone()
    file_sessions = [
        (session, session.sets, (session.session_date, session.workout_name))
        for session in parsed.sessions
    ]
    pairs = sorted({key for _session, _sets, key in file_sessions})
    stored_sessions = _stored_sessions(user, pairs)
    exercise_ids = {}
    for chunk in _chunked(parsed.exercises):
        exercise_ids.update(
            Exercise.objects.filter(owner=user, name__in=chunk).values_list("name", "id")
        )
    stored_sets, by_time = (
        _stored_sets([ref["id"] for ref in stored_sessions.values()])
        if stored_sessions
        else ({}, {})
    )

    new_sessions = 0
    existing_sessions = 0
    new_sets = 0
    existing_sets = 0
    conflicted = 0
    conflicts = []
    state_by_time = {}
    for session, sets, key in file_sessions:
        if key in stored_sessions:
            existing_sessions += 1
            session_id = stored_sessions[key]["id"]
        else:
            new_sessions += 1
            session_id = None
        for item in sets:
            exercise_id = exercise_ids.get(item.exercise_name)
            if session_id is None or exercise_id is None:
                new_sets += 1
                continue
            set_time = _file_set_time(item, zone)
            tkey = (session_id, exercise_id, set_time)
            values = _norm_values(
                (item.weight_kg, item.reps, item.rpe, item.distance, item.seconds)
            )
            state = state_by_time.setdefault(tkey, {"orders": set(), "values": {}})
            if tkey in by_time:
                state["values"].update(by_time[tkey])
                state["orders"].update(by_time[tkey].values())
            if values in state["values"]:
                existing_sets += 1
                continue
            order = item.set_order
            set_key = (session_id, exercise_id, order, set_time)
            if set_key in stored_sets:
                existing_sets += 1
                conflicted += 1
                if len(conflicts) < CONFLICT_SAMPLE_LIMIT:
                    stored_values = stored_sets[set_key]
                    changes = [
                        {
                            "field": field,
                            "label": FIELD_LABELS[field],
                            "stored": stored_value,
                            "file": file_value,
                        }
                        for field, stored_value, file_value in zip(
                            VALUE_FIELDS, stored_values, values, strict=True
                        )
                        if stored_value != file_value
                    ]
                    conflicts.append(
                        {
                            "session_date": session.session_date,
                            "workout_name": session.workout_name,
                            "exercise_name": item.exercise_name,
                            "set_order": order,
                            "changes": changes,
                        }
                    )
                continue
            if order in state["orders"]:
                order = max(state["orders"]) + 1
            state["orders"].add(order)
            state["values"][values] = order
            new_sets += 1
    dates = [session.session_date for session, _sets, _key in file_sessions]
    stored_range = WorkoutSession.objects.filter(owner=user).aggregate(
        first=Min("session_date"), last=Max("session_date")
    )
    return {
        "new_sessions": new_sessions,
        "existing_sessions": existing_sessions,
        "new_sets": new_sets,
        "existing_sets": existing_sets,
        "conflicted": conflicted,
        "file_range": (min(dates), max(dates)) if dates else None,
        "stored_range": (
            (stored_range["first"], stored_range["last"]) if stored_range["first"] else None
        ),
        "conflicts": conflicts,
    }


def stash_session(user, session: WorkoutSession) -> dict:
    return {
        "owner_id": user.id,
        "session": {
            "session_date": session.session_date.isoformat(),
            "program": session.program,
            "workout_name": session.workout_name,
            "start_time": session.start_time.isoformat(),
            "duration_min": session.duration_min,
        },
        "sets": [
            {
                "exercise_name": item.exercise.name,
                "set_order": item.set_order,
                "weight_kg": None if item.weight_kg is None else str(item.weight_kg),
                "reps": item.reps,
                "rpe": None if item.rpe is None else str(item.rpe),
                "distance": None if item.distance is None else str(item.distance),
                "seconds": None if item.seconds is None else str(item.seconds),
                "set_time": item.set_time.isoformat(),
                "volume_kg": str(item.volume_kg),
                "est_1rm_kg": None if item.est_1rm_kg is None else str(item.est_1rm_kg),
            }
            for item in session.sets.select_related("exercise").order_by("set_time", "set_order")
        ],
    }


def _decimal_or_none(value):
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _parse_aware(value: str, zone):
    parsed = datetime.fromisoformat(value)
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, zone)


def restore_stash(user, payload: dict) -> int:
    zone = timezone.get_default_timezone()
    with transaction.atomic():
        data = payload["session"]
        session, _created = WorkoutSession.objects.get_or_create(
            owner=user,
            session_date=date.fromisoformat(data["session_date"]),
            workout_name=data["workout_name"],
            defaults={
                "program": data.get("program") or "",
                "start_time": _parse_aware(data["start_time"], zone),
                "duration_min": data.get("duration_min"),
                "set_count": 0,
                "total_volume_kg": Decimal(0),
            },
        )
        existing = _stored_sets([session.id])[0]
        rows = []
        for item in payload["sets"]:
            exercise, _ = Exercise.objects.get_or_create(owner=user, name=item["exercise_name"])
            set_time = _parse_aware(item["set_time"], zone)
            if (session.id, exercise.id, item["set_order"], _utc(set_time)) in existing:
                continue
            rows.append(
                WorkoutSet(
                    owner=user,
                    session=session,
                    exercise=exercise,
                    set_order=item["set_order"],
                    weight_kg=_decimal_or_none(item.get("weight_kg")),
                    reps=int(item.get("reps") or 0),
                    rpe=_decimal_or_none(item.get("rpe")),
                    distance=_decimal_or_none(item.get("distance")),
                    seconds=_decimal_or_none(item.get("seconds")),
                    set_time=set_time,
                    volume_kg=_decimal_or_none(item.get("volume_kg")) or Decimal(0),
                    est_1rm_kg=_decimal_or_none(item.get("est_1rm_kg")),
                )
            )
        WorkoutSet.objects.bulk_create(rows)
        aggregate = WorkoutSet.objects.filter(session_id=session.id).aggregate(
            count=Count("id"), volume=Sum("volume_kg"), first=Min("set_time")
        )
        volume = aggregate["volume"] or Decimal(0)
        if not fits_decimal(volume, "total_volume"):
            raise ImportLimitError("The combined session volume is out of range.")
        WorkoutSession.objects.filter(id=session.id).update(
            set_count=aggregate["count"],
            total_volume_kg=volume,
            start_time=min(_utc(session.start_time), _utc(aggregate["first"])),
        )
    return len(rows)
