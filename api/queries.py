import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from workouts.models import ExerciseMeta, WorkoutSession, WorkoutSet

from .contract import ApiError
from .params import validate_date_range

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

SERIES_GROUP_BY = {
    "sessions": frozenset({"program"}),
    "volume": frozenset({"program", "muscle", "exercise"}),
    "volume-per-session": frozenset({"program"}),
    "training-time": frozenset({"program"}),
}

SESSION_SORT_KEYS = frozenset({"date", "program", "workout_name", "start_time", "volume", "sets"})
SET_SORT_KEYS = frozenset(
    {
        "date",
        "set_time",
        "exercise",
        "set_order",
        "weight",
        "reps",
        "rpe",
        "volume",
        "est_1rm",
    }
)


def round2(value):
    return round(float(value), 2)


def maybe_round2(value):
    return None if value is None else round2(value)


def num(value):
    return None if value is None else float(value)


def timestamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def today():
    return timezone.localdate()


def muscle_map(user):
    return dict(
        ExerciseMeta.objects.filter(owner=user).values_list("exercise_name", "muscle_group")
    )


def muscle_names(user, muscle):
    return list(
        ExerciseMeta.objects.filter(owner=user, muscle_group=muscle).values_list(
            "exercise_name", flat=True
        )
    )


def owned_sessions(
    user, *, start=None, end=None, program=None, exercise=None, muscle=None, weighted=None
):
    queryset = WorkoutSession.objects.filter(owner=user)
    if start is not None:
        queryset = queryset.filter(session_date__gte=start)
    if end is not None:
        queryset = queryset.filter(session_date__lte=end)
    if program is not None:
        queryset = queryset.filter(program=program)
    if exercise is not None:
        queryset = queryset.filter(sets__exercise__name=exercise)
    if muscle is not None:
        queryset = queryset.filter(sets__exercise__name__in=muscle_names(user, muscle))
    if weighted is True:
        queryset = queryset.filter(sets__weight_kg__isnull=False)
    elif weighted is False:
        queryset = queryset.exclude(sets__weight_kg__isnull=False)
    return queryset.distinct()


def owned_sets(
    user, *, start=None, end=None, program=None, exercise=None, muscle=None, weighted=None
):
    queryset = WorkoutSet.objects.filter(owner=user, session__owner=user).select_related(
        "session", "exercise"
    )
    if start is not None:
        queryset = queryset.filter(session__session_date__gte=start)
    if end is not None:
        queryset = queryset.filter(session__session_date__lte=end)
    if program is not None:
        queryset = queryset.filter(session__program=program)
    if exercise is not None:
        queryset = queryset.filter(exercise__name=exercise)
    if muscle is not None:
        queryset = queryset.filter(exercise__name__in=muscle_names(user, muscle))
    if weighted is not None:
        queryset = queryset.filter(weight_kg__isnull=not weighted)
    return queryset


def summary_data(user, start, end, program):
    sessions = list(owned_sessions(user, start=start, end=end, program=program))
    session_count = len(sessions)
    set_count = sum(session.set_count for session in sessions)
    volume = sum((session.total_volume_kg for session in sessions), Decimal(0))
    duration = sum(session.duration_min or 0 for session in sessions)

    if sessions:
        effective_start = start or min(item.session_date for item in sessions)
        effective_end = end or max(item.session_date for item in sessions)
        span = max((effective_end - effective_start).days + 1, 1)
        days_since_last = (today() - max(item.session_date for item in sessions)).days
    else:
        span = 1
        days_since_last = None

    weeks = span / 7
    return {
        "sessions": session_count,
        "sets": set_count,
        "volume_kg": round2(volume),
        "volume_t": round2(volume / 1000),
        "hours": round2(duration / 60),
        "sessions_per_week": round2(session_count / weeks),
        "avg_volume_per_session": round2(volume / session_count) if session_count else 0.0,
        "avg_session_min": round2(duration / session_count) if session_count else 0.0,
        "days_since_last_session": days_since_last,
    }


def bucket_start(value, bucket):
    if bucket == "day":
        return value
    if bucket == "week":
        return value - timedelta(days=value.weekday())
    if bucket == "month":
        return value.replace(day=1)
    return value.replace(month=1, day=1)


def iter_buckets(start, end, bucket):
    current = bucket_start(start, bucket)
    final = bucket_start(end, bucket)
    while current <= final:
        yield current
        if current == final:
            return
        if bucket == "day":
            current += timedelta(days=1)
        elif bucket == "week":
            current += timedelta(days=7)
        elif bucket == "month":
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            current = current.replace(year=current.year + 1)


def validate_series_options(metric, bucket, group_by, moving_average):
    if bucket not in {"day", "week", "month", "year"}:
        raise ApiError(422, "validation_error", "Unsupported bucket")
    if group_by is not None and group_by not in SERIES_GROUP_BY[metric]:
        raise ApiError(
            422,
            "validation_error",
            f"group_by={group_by} is not supported for this series",
        )
    if moving_average and bucket != "week":
        raise ApiError(422, "validation_error", "moving_average requires bucket=week")


def series_data(user, metric, bucket, group_by, start, end, moving_average):
    validate_series_options(metric, bucket, group_by, moving_average)
    mapping = muscle_map(user)

    def accumulator():
        return {
            "sessions": set(),
            "volume": 0.0,
            "duration": 0.0,
            "groups": defaultdict(lambda: {"value": 0.0, "sessions": set()}),
        }

    acc = defaultdict(accumulator)
    all_groups = set()

    def group_key(session, item=None):
        if group_by == "program":
            return session.program
        if group_by == "exercise":
            return item.exercise.name
        return mapping.get(item.exercise.name, "Other")

    if metric in {"sessions", "training-time", "volume-per-session"}:
        for session in owned_sessions(user, start=start, end=end):
            bucket_key = bucket_start(session.session_date, bucket)
            entry = acc[bucket_key]
            entry["sessions"].add(session.id)
            if metric == "training-time":
                hours = (session.duration_min or 0) / 60
                entry["duration"] += hours
            elif metric == "volume-per-session":
                entry["volume"] += float(session.total_volume_kg)
            if group_by:
                key = session.program
                entry["groups"][key]["value"] += (
                    1
                    if metric == "sessions"
                    else float(session.total_volume_kg)
                    if metric == "volume-per-session"
                    else (session.duration_min or 0) / 60
                )
                entry["groups"][key]["sessions"].add(session.id)
                all_groups.add(key)
    else:
        for item in owned_sets(user, start=start, end=end):
            bucket_key = bucket_start(item.session.session_date, bucket)
            entry = acc[bucket_key]
            volume = float(item.volume_kg)
            entry["volume"] += volume
            entry["sessions"].add(item.session_id)
            if group_by:
                key = group_key(item.session, item)
                entry["groups"][key]["value"] += volume
                entry["groups"][key]["sessions"].add(item.session_id)
                all_groups.add(key)

    if not acc and (start is None or end is None):
        return {"bucket": bucket, "group_by": group_by, "count": 0, "items": []}

    if acc:
        effective_start = start or min(acc)
        effective_end = end or max(acc)
    else:
        effective_start, effective_end = start, end
    validate_date_range(effective_start, effective_end)

    items = []
    values = []
    for current in iter_buckets(effective_start, effective_end, bucket):
        entry = acc.get(current)
        if metric == "sessions":
            value = len(entry["sessions"]) if entry else 0
        elif metric == "training-time":
            value = entry["duration"] if entry else 0.0
        elif metric == "volume-per-session":
            value = entry["volume"] / len(entry["sessions"]) if entry and entry["sessions"] else 0.0
        else:
            value = entry["volume"] if entry else 0.0
        groups = None
        if group_by:
            groups = []
            for key in sorted(all_groups):
                group_entry = entry["groups"].get(key) if entry else None
                if metric == "volume-per-session":
                    group_value = (
                        group_entry["value"] / len(group_entry["sessions"])
                        if group_entry and group_entry["sessions"]
                        else 0.0
                    )
                else:
                    group_value = group_entry["value"] if group_entry else 0.0
                groups.append({"key": key, "value": round2(group_value)})
        items.append(
            {
                "bucket_start": current.isoformat(),
                "value": round2(value),
                "groups": groups,
            }
        )
        values.append(value)

    if moving_average:
        for index, item in enumerate(items):
            window = values[max(0, index - 3) : index + 1]
            item["value_4wma"] = round2(sum(window) / len(window)) if len(window) == 4 else None

    return {"bucket": bucket, "group_by": group_by, "count": len(items), "items": items}


def breakdown_data(user, dimension, start, end, limit):
    if dimension in {"weekday", "program"}:
        buckets = defaultdict(lambda: {"sessions": 0, "sets": 0, "volume": Decimal(0)})
        if dimension == "weekday":
            for name in WEEKDAYS:
                buckets[name]
        for session in owned_sessions(user, start=start, end=end):
            key = (
                WEEKDAYS[session.session_date.weekday()]
                if dimension == "weekday"
                else session.program
            )
            entry = buckets[key]
            entry["sessions"] += 1
            entry["sets"] += session.set_count
            entry["volume"] += session.total_volume_kg
    else:
        mapping = muscle_map(user)
        buckets = defaultdict(lambda: {"session_ids": set(), "sets": 0, "volume": Decimal(0)})
        for item in owned_sets(user, start=start, end=end):
            key = (
                mapping.get(item.exercise.name, "Other")
                if dimension == "muscle"
                else item.exercise.name
            )
            entry = buckets[key]
            entry["session_ids"].add(item.session_id)
            entry["sets"] += 1
            entry["volume"] += item.volume_kg

    rows = [
        (
            key,
            len(entry["session_ids"]) if "session_ids" in entry else entry["sessions"],
            entry["sets"],
            entry["volume"],
        )
        for key, entry in buckets.items()
    ]
    if dimension == "weekday":
        rows.sort(key=lambda row: WEEKDAYS.index(row[0]))
    else:
        rows.sort(key=lambda row: (-row[3], row[0]))

    items = [
        {"key": key, "sessions": sessions, "sets": sets, "volume_kg": round2(volume)}
        for key, sessions, sets, volume in rows[:limit]
    ]
    return {"count": len(rows), "items": items}


def progress_data(user, name, start, end):
    by_date = defaultdict(list)
    for item in owned_sets(user, start=start, end=end, exercise=name):
        by_date[item.session.session_date].append(item)

    items = []
    for day in sorted(by_date):
        entries = by_date[day]
        estimates = [item.est_1rm_kg for item in entries if item.est_1rm_kg is not None]
        weights = [item.weight_kg for item in entries if item.weight_kg is not None]
        items.append(
            {
                "date": day.isoformat(),
                "best_est_1rm_kg": round2(max(estimates)) if estimates else None,
                "top_weight_kg": round2(max(weights)) if weights else None,
                "max_reps": max(item.reps for item in entries),
                "volume_kg": round2(sum((item.volume_kg for item in entries), Decimal(0))),
            }
        )
    return {"count": len(items), "items": items}


def exercise_record_data(user, name, start, end):
    by_reps = defaultdict(list)
    for item in owned_sets(user, start=start, end=end, exercise=name):
        by_reps[item.reps].append(item)

    items = []
    for reps in sorted(by_reps):
        best = max(
            by_reps[reps],
            key=lambda item: (
                item.weight_kg or Decimal(0),
                item.est_1rm_kg or Decimal(0),
                item.set_time,
            ),
        )
        items.append(
            {
                "reps": reps,
                "top_weight_kg": maybe_round2(best.weight_kg),
                "best_est_1rm_kg": maybe_round2(best.est_1rm_kg),
                "volume_kg": round2(best.volume_kg),
                "set_time": timestamp(best.set_time),
            }
        )
    return {"count": len(items), "items": items}


def est_1rm_record_data(user):
    by_exercise = defaultdict(list)
    for item in owned_sets(user):
        if item.est_1rm_kg is not None:
            by_exercise[item.exercise.name].append(item)

    items = []
    for name, entries in by_exercise.items():
        best = max(
            entries,
            key=lambda item: (
                item.est_1rm_kg,
                item.reps,
                item.weight_kg or Decimal(0),
                item.set_time,
            ),
        )
        items.append(
            {
                "exercise": name,
                "est_1rm_kg": round2(best.est_1rm_kg),
                "reps": best.reps,
                "weight_kg": round2(best.weight_kg),
                "set_time": timestamp(best.set_time),
            }
        )
    items.sort(key=lambda row: -row["est_1rm_kg"])
    return {"count": len(items), "items": items}


def bodyweight_record_data(user):
    by_exercise = defaultdict(list)
    for item in owned_sets(user):
        if item.weight_kg is None:
            by_exercise[item.exercise.name].append(item)

    items = []
    for name, entries in by_exercise.items():
        best = max(entries, key=lambda item: (item.reps, item.set_time))
        items.append(
            {
                "exercise": name,
                "reps": best.reps,
                "set_time": timestamp(best.set_time),
                "seconds": maybe_round2(best.seconds),
                "distance": maybe_round2(best.distance),
            }
        )
    items.sort(key=lambda row: -row["reps"])
    return {"count": len(items), "items": items}


def yearly_data(user):
    buckets = defaultdict(lambda: {"sessions": 0, "sets": 0, "volume": Decimal(0), "duration": 0})
    for session in owned_sessions(user):
        entry = buckets[session.session_date.year]
        entry["sessions"] += 1
        entry["sets"] += session.set_count
        entry["volume"] += session.total_volume_kg
        entry["duration"] += session.duration_min or 0

    items = []
    for year in sorted(buckets):
        entry = buckets[year]
        volume = entry["volume"]
        items.append(
            {
                "year": year,
                "sessions": entry["sessions"],
                "sets": entry["sets"],
                "volume_kg": round2(volume),
                "volume_t": round2(volume / 1000),
                "hours": round2(entry["duration"] / 60),
            }
        )
    return {"count": len(items), "items": items}


def _totals(sessions):
    sessions = list(sessions)
    volume = sum((item.total_volume_kg for item in sessions), Decimal(0))
    duration = sum(item.duration_min or 0 for item in sessions)
    return {
        "sessions": len(sessions),
        "sets": sum(item.set_count for item in sessions),
        "volume_kg": float(volume),
        "hours": duration / 60,
    }


def _round_totals(totals):
    return {key: round2(value) for key, value in totals.items()}


def _scaled(totals, factor):
    return {key: round2(value * factor) for key, value in totals.items()}


def _cutoff(year, as_of):
    day = min(as_of.day, calendar.monthrange(year, as_of.month)[1])
    return date(year, as_of.month, day)


def pace_data(user, year, as_of):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    previous = year - 1
    cutoff = _cutoff(year, as_of)

    with transaction.atomic():
        ytd = _totals(owned_sessions(user, start=year_start, end=cutoff))
        last_ytd = _totals(
            owned_sessions(user, start=date(previous, 1, 1), end=_cutoff(previous, as_of))
        )
        last_full = _totals(
            owned_sessions(user, start=date(previous, 1, 1), end=date(previous, 12, 31))
        )
        yearly = yearly_data(user)["items"]

    days_in_year = (year_end - year_start).days + 1
    elapsed = max(1, min((cutoff - year_start).days + 1, days_in_year))
    remaining_weeks = max(0, (days_in_year - elapsed) / 7)

    projected = _scaled(ytd, days_in_year / elapsed)
    needed = {
        key: round2(max(last_full[key] - ytd[key], 0) / remaining_weeks) if remaining_weeks else 0.0
        for key in ytd
    }

    cumulative_sessions = 0
    cumulative_volume = 0.0
    pace = []
    for row in yearly:
        if row["year"] > year:
            continue
        cumulative_sessions += row["sessions"]
        cumulative_volume += row["volume_kg"]
        pace.append(
            {
                "year": row["year"],
                "sessions": row["sessions"],
                "volume_kg": row["volume_kg"],
                "cumulative_sessions": cumulative_sessions,
                "cumulative_volume_kg": round2(cumulative_volume),
            }
        )

    return {
        "year": year,
        "ytd": _round_totals(ytd),
        "last_year_to_date": _round_totals(last_ytd),
        "projected": projected,
        "needed_per_week": needed,
        "pace": pace,
    }


def set_record(item, mapping):
    return {
        "id": item.id,
        "session_id": item.session_id,
        "session_date": item.session.session_date,
        "exercise": item.exercise.name,
        "muscle_group": mapping.get(item.exercise.name, "Other"),
        "set_order": item.set_order,
        "weight_kg": num(item.weight_kg),
        "reps": item.reps,
        "rpe": num(item.rpe),
        "distance": num(item.distance),
        "seconds": num(item.seconds),
        "set_time": item.set_time,
        "volume_kg": round2(item.volume_kg),
        "est_1rm_kg": maybe_round2(item.est_1rm_kg),
    }


def session_record(session):
    return {
        "id": session.id,
        "session_date": session.session_date,
        "program": session.program,
        "workout_name": session.workout_name,
        "start_time": session.start_time,
        "duration_min": session.duration_min,
        "set_count": session.set_count,
        "total_volume_kg": round2(session.total_volume_kg),
    }


def public_set(record):
    return {
        "id": record["id"],
        "session_id": record["session_id"],
        "session_date": record["session_date"].isoformat(),
        "exercise": record["exercise"],
        "muscle_group": record["muscle_group"],
        "set_order": record["set_order"],
        "weight_kg": record["weight_kg"],
        "reps": record["reps"],
        "rpe": record["rpe"],
        "distance": record["distance"],
        "seconds": record["seconds"],
        "set_time": timestamp(record["set_time"]),
        "volume_kg": record["volume_kg"],
        "est_1rm_kg": record["est_1rm_kg"],
    }


def public_session(record):
    return {
        "id": record["id"],
        "session_date": record["session_date"].isoformat(),
        "program": record["program"],
        "workout_name": record["workout_name"],
        "start_time": timestamp(record["start_time"]),
        "duration_min": record["duration_min"],
        "set_count": record["set_count"],
        "total_volume_kg": record["total_volume_kg"],
    }
