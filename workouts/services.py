from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from parsing import ParsedWorkouts, classify_muscle, parse_workouts

from .models import Exercise, ExerciseMeta, WorkoutSession, WorkoutSet


class EmptyImportError(ValueError):
    """Raised when an export contains no importable sets."""


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


def _chunked(items, size=KEY_CHUNK):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _dedup_file_sets(parsed: ParsedWorkouts):
    seen = set()
    deduped = []
    for session in parsed.sessions:
        sets = []
        for item in session.sets:
            key = (
                session.session_date,
                session.workout_name,
                item.exercise_name,
                item.set_order,
                item.set_time,
            )
            if key not in seen:
                seen.add(key)
                sets.append(item)
        deduped.append((session, tuple(sets), (session.session_date, session.workout_name)))
    return deduped


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
    for chunk in _chunked(session_ids):
        rows = WorkoutSet.objects.filter(session_id__in=chunk).values_list(
            "session_id", "exercise_id", "set_order", "set_time", *VALUE_FIELDS
        )
        for row in rows:
            stored[row[:4]] = row[4:]
    return stored


def _session_id(ref):
    return ref["id"] if isinstance(ref, dict) else ref.id


CONFLICT_SAMPLE_LIMIT = 20


def compare_import(user, parsed: ParsedWorkouts) -> dict:
    zone = timezone.get_default_timezone()
    file_sessions = _dedup_file_sets(parsed)
    pairs = sorted({key for _session, _sets, key in file_sessions})
    stored_sessions = _stored_sessions(user, pairs)
    exercise_ids = dict(
        Exercise.objects.filter(owner=user, name__in=parsed.exercises).values_list("name", "id")
    )
    stored_sets = (
        _stored_sets([ref["id"] for ref in stored_sessions.values()]) if stored_sessions else {}
    )

    new_sessions = 0
    existing_sessions = 0
    new_sets = 0
    existing_sets = 0
    conflicted = 0
    conflicts = []
    for session, sets, key in file_sessions:
        if key in stored_sessions:
            existing_sessions += 1
            session_id = stored_sessions[key]["id"]
        else:
            new_sessions += 1
            session_id = None
        for item in sets:
            if session_id is None or item.exercise_name not in exercise_ids:
                new_sets += 1
                continue
            set_key = (
                session_id,
                exercise_ids[item.exercise_name],
                item.set_order,
                timezone.make_aware(item.set_time, zone),
            )
            values = (item.weight_kg, item.reps, item.rpe, item.distance, item.seconds)
            if set_key not in stored_sets:
                new_sets += 1
            else:
                existing_sets += 1
                if stored_sets[set_key] != values:
                    conflicted += 1
                    if len(conflicts) < CONFLICT_SAMPLE_LIMIT:
                        stored_values = stored_sets[set_key]
                        conflicts.append(
                            {
                                "session_date": session.session_date,
                                "workout_name": session.workout_name,
                                "exercise_name": item.exercise_name,
                                "set_order": item.set_order,
                                "set_time": item.set_time,
                                "stored_weight_kg": stored_values[0],
                                "file_weight_kg": item.weight_kg,
                                "stored_reps": stored_values[1],
                                "file_reps": item.reps,
                            }
                        )
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

        file_sessions = _dedup_file_sets(parsed)
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

        stored_sets = _stored_sets([_session_id(ref) for ref in session_refs.values()])

        added_sets = 0
        skipped_sets = 0
        conflicted = 0
        set_rows = []
        gained = set()
        for _session, sets, key in file_sessions:
            session_id = _session_id(session_refs[key])
            for item in sets:
                exercise = exercises[item.exercise_name]
                set_time = timezone.make_aware(item.set_time, zone)
                set_key = (session_id, exercise.id, item.set_order, set_time)
                values = (item.weight_kg, item.reps, item.rpe, item.distance, item.seconds)
                if set_key in stored_sets:
                    skipped_sets += 1
                    if stored_sets[set_key] != values:
                        conflicted += 1
                    continue
                added_sets += 1
                gained.add(key)
                set_rows.append(
                    WorkoutSet(
                        owner=user,
                        session_id=session_id,
                        exercise=exercise,
                        set_order=item.set_order,
                        weight_kg=item.weight_kg,
                        reps=item.reps,
                        rpe=item.rpe,
                        distance=item.distance,
                        seconds=item.seconds,
                        set_time=set_time,
                        volume_kg=item.volume_kg,
                        est_1rm_kg=item.est_1rm_kg,
                    )
                )
        WorkoutSet.objects.bulk_create(set_rows)

        if gained:
            id_to_ref = {_session_id(session_refs[key]): session_refs[key] for key in gained}
            for chunk in _chunked(id_to_ref):
                rows = (
                    WorkoutSet.objects.filter(session_id__in=chunk)
                    .values("session_id")
                    .annotate(count=Count("id"), volume=Sum("volume_kg"), first=Min("set_time"))
                )
                for row in rows:
                    ref = id_to_ref[row["session_id"]]
                    start = ref["start_time"] if isinstance(ref, dict) else ref.start_time
                    WorkoutSession.objects.filter(id=row["session_id"]).update(
                        set_count=row["count"],
                        total_volume_kg=row["volume"] or Decimal(0),
                        start_time=min(start, row["first"]),
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
        existing = _stored_sets([session.id])
        rows = []
        for item in payload["sets"]:
            exercise, _ = Exercise.objects.get_or_create(owner=user, name=item["exercise_name"])
            set_time = _parse_aware(item["set_time"], zone)
            if (session.id, exercise.id, item["set_order"], set_time) in existing:
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
        WorkoutSession.objects.filter(id=session.id).update(
            set_count=aggregate["count"],
            total_volume_kg=aggregate["volume"] or Decimal(0),
            start_time=min(session.start_time, aggregate["first"]),
        )
    return len(rows)
