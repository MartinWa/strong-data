from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

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
VALUE_PRECISION = {
    "weight_kg": Decimal("0.01"),
    "reps": None,
    "rpe": Decimal("0.1"),
    "distance": Decimal("0.01"),
    "seconds": Decimal("0.01"),
    "volume_kg": Decimal("0.01"),
    "est_1rm_kg": Decimal("0.01"),
}
VALUE_FIELDS = tuple(VALUE_PRECISION)
FIELD_LABELS = {
    "weight_kg": "weight",
    "reps": "reps",
    "rpe": "rpe",
    "distance": "distance",
    "seconds": "seconds",
    "volume_kg": "volume",
    "est_1rm_kg": "estimated 1RM",
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
            .values_list(
                "id",
                "session_date",
                "workout_name",
                "start_time",
                "duration_min",
                "import_time_zone",
            )
        )
        for pk, session_date, workout_name, start_time, duration_min, import_time_zone in rows:
            stored[(session_date, workout_name)] = {
                "id": pk,
                "start_time": start_time,
                "duration_min": duration_min,
                "import_time_zone": import_time_zone,
            }
    return stored


def _stored_sets(session_ids):
    stored = defaultdict(list)
    for chunk in _chunked(session_ids):
        rows = WorkoutSet.objects.filter(session_id__in=chunk).values_list(
            "session_id", "exercise_id", "set_time", "set_order", "source_set_order", *VALUE_FIELDS
        )
        for session_id, exercise_id, set_time, order, source_order, *values in rows:
            stored[(session_id, exercise_id, _utc(set_time))].append(
                (order, source_order or order, _norm_values(values))
            )
    return stored


def _session_id(ref):
    return ref["id"] if isinstance(ref, dict) else ref.id


def _allocate_set_order(preferred_order, taken, fallback_orders):
    order = next(fallback_orders) if preferred_order in taken else preferred_order
    taken.add(order)
    return order


def _classify(file_sessions, stored_sessions, exercise_ids, stored_sets, default_zone):
    file_groups = defaultdict(lambda: defaultdict(list))
    for _session, sets, key in file_sessions:
        stored = stored_sessions.get(key)
        session_key = stored["id"] if stored else key
        zone = ZoneInfo(stored["import_time_zone"]) if stored else default_zone
        for item in sets:
            exercise_key = exercise_ids.get(item.exercise_name, item.exercise_name)
            set_time = _file_set_time(item, zone)
            values = _norm_values(getattr(item, field) for field in VALUE_FIELDS)
            by_source_order = file_groups[(session_key, exercise_key, set_time)]
            by_source_order[item.set_order].append((key, item, values))

    decisions = []
    for group_key, file_by_source_order in file_groups.items():
        set_time = group_key[2]
        stored_by_source_order = defaultdict(list)
        taken = set()
        for order, source_order, values in stored_sets.get(group_key, ()):
            stored_by_source_order[source_order].append(values)
            taken.add(order)
        fallback_orders = count(max(taken | file_by_source_order.keys()) + 1)
        for source_order, entries in file_by_source_order.items():
            stored_values = stored_by_source_order.get(source_order, ())
            seen = set(stored_values)
            file_values = {values for _key, _item, values in entries}
            unmatched = iter(values for values in stored_values if values not in file_values)
            for key, item, values in entries:
                if values in seen:
                    decisions.append((key, item, source_order, "skip", values, set_time, None))
                    continue
                seen.add(values)
                previous_values = next(unmatched, None)
                if previous_values is not None:
                    decisions.append(
                        (key, item, source_order, "conflict", values, set_time, previous_values)
                    )
                    continue
                order = _allocate_set_order(source_order, taken, fallback_orders)
                decisions.append((key, item, order, "add", values, set_time, None))
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
                import_time_zone=zone.key,
                duration_min=session.duration_min,
                set_count=len(sets),
                total_volume_kg=sum((item.volume_kg for item in sets), Decimal(0)),
            )
            for session, sets, key in pending
        )
        for (_session, _sets, key), row in zip(pending, created, strict=True):
            session_refs[key] = row

        session_ids = {key: _session_id(ref) for key, ref in session_refs.items()}
        exercise_ids = {name: exercise.id for name, exercise in exercises.items()}
        stored_sets = _stored_sets(ref["id"] for ref in stored.values())
        decisions = _classify(file_sessions, stored, exercise_ids, stored_sets, zone)

        added_sets = 0
        skipped_sets = 0
        conflicted = 0
        set_rows = []
        for key, item, order, decision, values, set_time, _previous_values in decisions:
            if decision == "skip":
                skipped_sets += 1
                continue
            if decision == "conflict":
                skipped_sets += 1
                conflicted += 1
                continue
            added_sets += 1
            weight_kg, reps, rpe, distance, seconds, volume_kg, est_1rm_kg = values
            set_rows.append(
                WorkoutSet(
                    owner=user,
                    session_id=session_ids[key],
                    exercise=exercises[item.exercise_name],
                    set_order=order,
                    source_set_order=item.set_order if order != item.set_order else None,
                    weight_kg=weight_kg,
                    reps=reps,
                    rpe=rpe,
                    distance=distance,
                    seconds=seconds,
                    set_time=set_time,
                    volume_kg=volume_kg,
                    est_1rm_kg=est_1rm_kg,
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
    stored_sets = _stored_sets(ref["id"] for ref in stored_sessions.values())

    decisions = _classify(file_sessions, stored_sessions, exercise_ids, stored_sets, zone)

    existing_sessions = len(stored_sessions)
    new_sessions = len(pairs) - existing_sessions
    new_sets = 0
    skipped_sets = 0
    conflicted = 0
    conflicts = []
    for key, item, order, decision, values, _set_time, previous_values in decisions:
        if decision == "skip":
            skipped_sets += 1
            continue
        if decision == "conflict":
            skipped_sets += 1
            conflicted += 1
            if len(conflicts) < CONFLICT_SAMPLE_LIMIT:
                changes = [
                    {
                        "field": field,
                        "label": FIELD_LABELS[field],
                        "stored": stored_value,
                        "file": file_value,
                    }
                    for field, stored_value, file_value in zip(
                        VALUE_FIELDS, previous_values, values, strict=True
                    )
                    if stored_value != file_value
                ]
                conflicts.append(
                    {
                        "session_date": key[0],
                        "workout_name": key[1],
                        "exercise_name": item.exercise_name,
                        "set_order": order,
                        "changes": changes,
                    }
                )
            continue
        new_sets += 1
    dates = [session.session_date for session, _sets, _key in file_sessions]
    stored_range = WorkoutSession.objects.filter(owner=user).aggregate(
        first=Min("session_date"), last=Max("session_date")
    )
    return {
        "new_sessions": new_sessions,
        "existing_sessions": existing_sessions,
        "new_sets": new_sets,
        "skipped_sets": skipped_sets,
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
            "import_time_zone": session.import_time_zone,
            "duration_min": session.duration_min,
        },
        "sets": [
            {
                "exercise_name": item.exercise.name,
                "set_order": item.set_order,
                "source_set_order": item.source_set_order,
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
    data = payload["session"]
    duration_min = data.get("duration_min")
    stash_zone = ZoneInfo(data.get("import_time_zone") or timezone.get_default_timezone_name())
    with transaction.atomic():
        session, _created = WorkoutSession.objects.get_or_create(
            owner=user,
            session_date=date.fromisoformat(data["session_date"]),
            workout_name=data["workout_name"],
            defaults={
                "program": data.get("program") or "",
                "start_time": _parse_aware(data["start_time"], stash_zone),
                "import_time_zone": stash_zone.key,
                "duration_min": duration_min,
                "set_count": 0,
                "total_volume_kg": Decimal(0),
            },
        )
        session_zone = ZoneInfo(session.import_time_zone)
        stored_sets = _stored_sets([session.id])
        exercise_ids = {}
        items_by_time = defaultdict(list)
        for item in payload["sets"]:
            name = item["exercise_name"]
            if name not in exercise_ids:
                exercise, _ = Exercise.objects.get_or_create(owner=user, name=name)
                exercise_ids[name] = exercise.id
            set_time = _parse_aware(item["set_time"], stash_zone)
            if session_zone != stash_zone:
                set_time = set_time.astimezone(stash_zone).replace(tzinfo=session_zone, fold=0)
            items_by_time[(session.id, exercise_ids[name], _utc(set_time))].append(item)

        rows = []
        for group_key, items in items_by_time.items():
            _session_id, exercise_id, set_time = group_key
            stored_group = stored_sets.get(group_key, ())
            taken = {order for order, _source_order, _values in stored_group}
            reserved = {item["set_order"] for item in items}
            fallback_orders = count(max(taken | reserved) + 1)
            remaining = Counter(
                (source_order, values) for _order, source_order, values in stored_group
            )
            for item in items:
                preferred_order = item["set_order"]
                source_order = item.get("source_set_order") or preferred_order
                values = _norm_values(
                    (
                        _decimal_or_none(item.get("weight_kg")),
                        item.get("reps") or 0,
                        _decimal_or_none(item.get("rpe")),
                        _decimal_or_none(item.get("distance")),
                        _decimal_or_none(item.get("seconds")),
                        _decimal_or_none(item.get("volume_kg")) or Decimal(0),
                        _decimal_or_none(item.get("est_1rm_kg")),
                    )
                )
                signature = (source_order, values)
                if remaining[signature]:
                    remaining[signature] -= 1
                    continue
                order = _allocate_set_order(preferred_order, taken, fallback_orders)
                weight_kg, reps, rpe, distance, seconds, volume_kg, est_1rm_kg = values
                rows.append(
                    WorkoutSet(
                        owner=user,
                        session=session,
                        exercise_id=exercise_id,
                        set_order=order,
                        source_set_order=source_order if order != source_order else None,
                        weight_kg=weight_kg,
                        reps=reps,
                        rpe=rpe,
                        distance=distance,
                        seconds=seconds,
                        set_time=set_time,
                        volume_kg=volume_kg,
                        est_1rm_kg=est_1rm_kg,
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
            duration_min=session.duration_min if session.duration_min is not None else duration_min,
        )
    return len(rows)
