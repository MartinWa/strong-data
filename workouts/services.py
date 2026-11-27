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


def _classify(file_sessions, session_ids, exercise_ids, stored, by_time, zone):
    """Decide per file set: "skip", "conflict" or "add" (with a collision-free
    set order). Identity is (timestamp group, source order); a values-based
    fallback only covers rows renumbered away from their source order, i.e.
    stored under an order the file itself does not use. Unsaved entities get
    per-entity placeholder keys so they never conflate.

    Decisions carry (session_key, item, set_order, decision, values, set_time).
    """
    entries = []
    reserved = {}
    for _session, sets, key in file_sessions:
        session_id = session_ids[key]
        sid_key = session_id if session_id is not None else ("new-session", key)
        for item in sets:
            exercise_id = exercise_ids.get(item.exercise_name)
            ex_key = (
                exercise_id if exercise_id is not None else ("new-exercise", item.exercise_name)
            )
            set_time = _file_set_time(item, zone)
            entries.append((key, sid_key, ex_key, set_time, item))
            reserved.setdefault((sid_key, ex_key, set_time), set()).add(item.set_order)

    decisions = []
    group_state = {}
    for key, sid_key, ex_key, set_time, item in entries:
        values = _norm_values((item.weight_kg, item.reps, item.rpe, item.distance, item.seconds))
        tkey = (sid_key, ex_key, set_time)
        state = group_state.get(tkey)
        if state is None:
            real_key = (
                (sid_key, ex_key, set_time)
                if isinstance(sid_key, int) and isinstance(ex_key, int)
                else None
            )
            stored_group = by_time.get(real_key, {}) if real_key else {}
            state = group_state[tkey] = {
                "reserved": reserved[tkey],
                "taken": set(stored_group.values()),
                "stored_values": stored_group,
                "source_values": {},
            }
        order = item.set_order
        if isinstance(sid_key, int) and isinstance(ex_key, int):
            set_key = (sid_key, ex_key, order, set_time)
            if set_key in stored:
                if stored[set_key] == values or (
                    values in state["stored_values"]
                    and state["stored_values"][values] not in state["reserved"]
                ):
                    decisions.append((key, item, order, "skip", values, set_time))
                else:
                    decisions.append((key, item, order, "conflict", values, set_time))
                continue
        source_values = state["source_values"].setdefault(order, set())
        if order in state["taken"]:
            if values in source_values:
                decisions.append((key, item, order, "skip", values, set_time))
                continue
            order = max(state["reserved"] | state["taken"]) + 1
        source_values.add(values)
        state["taken"].add(order)
        decisions.append((key, item, order, "add", values, set_time))
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

        session_ids = {key: _session_id(ref) for key, ref in session_refs.items()}
        exercise_ids = {name: exercise.id for name, exercise in exercises.items()}
        stored_sets, by_time = _stored_sets(list(session_ids.values()))
        decisions = _classify(file_sessions, session_ids, exercise_ids, stored_sets, by_time, zone)

        added_sets = 0
        skipped_sets = 0
        conflicted = 0
        set_rows = []
        for key, item, order, decision, _values, _set_time in decisions:
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
                    session_id=session_ids[key],
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
    session_ids = {
        key: (stored_sessions[key]["id"] if key in stored_sessions else None) for key in pairs
    }
    exercise_ids = {}
    for chunk in _chunked(parsed.exercises):
        exercise_ids.update(
            Exercise.objects.filter(owner=user, name__in=chunk).values_list("name", "id")
        )
    existing_ids = [ref["id"] for ref in stored_sessions.values()]
    stored_sets, by_time = _stored_sets(existing_ids) if existing_ids else ({}, {})

    decisions = _classify(file_sessions, session_ids, exercise_ids, stored_sets, by_time, zone)

    new_sessions = sum(1 for session_id in session_ids.values() if session_id is None)
    existing_sessions = len(session_ids) - new_sessions
    new_sets = 0
    existing_sets = 0
    conflicted = 0
    conflicts = []
    for key, item, order, decision, values, set_time in decisions:
        if decision == "skip":
            existing_sets += 1
            continue
        if decision == "conflict":
            existing_sets += 1
            conflicted += 1
            if len(conflicts) < CONFLICT_SAMPLE_LIMIT:
                set_key = (session_ids[key], exercise_ids[item.exercise_name], order, set_time)
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
        stored, by_time = _stored_sets([session.id])
        items_by_time = {}
        for item in payload["sets"]:
            exercise, _ = Exercise.objects.get_or_create(owner=user, name=item["exercise_name"])
            set_time = _utc(_parse_aware(item["set_time"], zone))
            weight_kg = _decimal_or_none(item.get("weight_kg"))
            rpe = _decimal_or_none(item.get("rpe"))
            distance = _decimal_or_none(item.get("distance"))
            seconds = _decimal_or_none(item.get("seconds"))
            reps = int(item.get("reps") or 0)
            values = _norm_values((weight_kg, reps, rpe, distance, seconds))
            tkey = (session.id, exercise.id, set_time)
            items_by_time.setdefault(tkey, []).append((item, exercise, set_time, values))

        rows = []
        for tkey, items in items_by_time.items():
            stored_here = [key for key in stored if key[:2] + (key[3],) == tkey]
            by_values = {}
            for skey in stored_here:
                by_values.setdefault(stored[skey], []).append(skey[2])
            reserved = {item["set_order"] for item, _ex, _st, _v in items}
            taken = {skey[2] for skey in stored_here}
            consumed = set()
            deferred = []
            for item, exercise, set_time, values in items:
                order = item["set_order"]
                if order in by_values.get(values, []) and order not in consumed:
                    consumed.add(order)
                    continue
                deferred.append((item, exercise, set_time, values))
            for item, exercise, set_time, values in deferred:
                candidates = [o for o in by_values.get(values, []) if o not in consumed]
                if candidates:
                    consumed.add(candidates[0])
                    continue
                order = item["set_order"]
                if order in taken or order in consumed:
                    order = max(reserved | taken | consumed) + 1
                taken.add(order)
                rows.append(
                    WorkoutSet(
                        owner=user,
                        session=session,
                        exercise=exercise,
                        set_order=order,
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
