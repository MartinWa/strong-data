import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Max, Min, Q, Sum, Window
from django.db.models.fields import DateField
from django.db.models.functions import RowNumber, TruncMonth, TruncWeek, TruncYear
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
    totals = owned_sessions(user, start=start, end=end, program=program).aggregate(
        sessions=Count("id"),
        sets=Sum("set_count"),
        volume=Sum("total_volume_kg"),
        duration=Sum("duration_min"),
        first=Min("session_date"),
        last=Max("session_date"),
    )
    session_count = totals["sessions"] or 0
    set_count = totals["sets"] or 0
    volume = totals["volume"] or Decimal(0)
    duration = totals["duration"] or 0

    if session_count:
        effective_start = start or totals["first"]
        effective_end = end or totals["last"]
        span = max((effective_end - effective_start).days + 1, 1)
        days_since_last = (today() - totals["last"]).days
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


TRUNC_BUCKETS = {
    "week": TruncWeek,
    "month": TruncMonth,
    "year": TruncYear,
}


def _bucket_expression(bucket, field="session_date"):
    if bucket == "day":
        return F(field)
    return TRUNC_BUCKETS[bucket](field, output_field=DateField())


def _series_bounds(user, start, end, program):
    return owned_sessions(user, start=start, end=end, program=program).aggregate(
        first=Min("session_date"), last=Max("session_date")
    )


def per_session(volume, sessions):
    if not sessions:
        return 0.0
    return Decimal(volume) / Decimal(sessions)


def _accumulated_series_data(user, metric, bucket, group_by, start, end, moving_average, program):
    mapping = muscle_map(user)
    zero = Decimal(0) if metric in {"volume", "volume-per-session", "training-time"} else 0

    def accumulator():
        return {
            "sessions": set(),
            "volume": zero,
            "duration": zero,
            "groups": defaultdict(lambda: {"value": zero, "sessions": set()}),
        }

    acc = defaultdict(accumulator)
    dates = []
    all_groups = set()

    if metric in {"sessions", "training-time", "volume-per-session"}:
        rows = owned_sessions(user, start=start, end=end, program=program).values(
            "id", "session_date", "program", "duration_min", "total_volume_kg"
        )
        for row in rows:
            dates.append(row["session_date"])
            entry = acc[bucket_start(row["session_date"], bucket)]
            entry["sessions"].add(row["id"])
            if metric == "training-time":
                entry["duration"] += Decimal(row["duration_min"] or 0)
            elif metric == "volume-per-session":
                entry["volume"] += row["total_volume_kg"]
            key = row["program"]
            entry["groups"][key]["value"] += (
                1
                if metric == "sessions"
                else row["total_volume_kg"]
                if metric == "volume-per-session"
                else Decimal(row["duration_min"] or 0)
            )
            entry["groups"][key]["sessions"].add(row["id"])
            all_groups.add(key)
    else:
        rows = owned_sets(user, start=start, end=end, program=program).values(
            "session_id", "volume_kg", "session__session_date", "session__program", "exercise__name"
        )
        for row in rows:
            dates.append(row["session__session_date"])
            entry = acc[bucket_start(row["session__session_date"], bucket)]
            volume = row["volume_kg"]
            entry["volume"] += volume
            entry["sessions"].add(row["session_id"])
            if group_by == "program":
                key = row["session__program"]
            elif group_by == "exercise":
                key = row["exercise__name"]
            else:
                key = mapping.get(row["exercise__name"], "Other")
            entry["groups"][key]["value"] += volume
            entry["groups"][key]["sessions"].add(row["session_id"])
            all_groups.add(key)

    if not acc and (start is None or end is None):
        return {"bucket": bucket, "group_by": group_by, "count": 0, "items": []}

    effective_start = start if start is not None else min(dates)
    effective_end = end if end is not None else max(dates)
    validate_date_range(effective_start, effective_end)

    items = []
    values = []
    for current in iter_buckets(effective_start, effective_end, bucket):
        entry = acc.get(current)
        if metric == "sessions":
            value = len(entry["sessions"]) if entry else 0
        elif metric == "training-time":
            value = (entry["duration"] if entry else zero) / Decimal(60)
        elif metric == "volume-per-session":
            value = per_session(entry["volume"], len(entry["sessions"])) if entry else 0.0
        else:
            value = entry["volume"] if entry else zero
        groups = None
        if group_by:
            groups = []
            for key in sorted(all_groups):
                group_entry = entry["groups"].get(key) if entry else None
                if metric == "volume-per-session":
                    group_value = (
                        per_session(group_entry["value"], len(group_entry["sessions"]))
                        if group_entry
                        else 0.0
                    )
                elif metric == "training-time":
                    group_value = (group_entry["value"] if group_entry else zero) / Decimal(60)
                else:
                    group_value = group_entry["value"] if group_entry else zero
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


def series_data(user, metric, bucket, group_by, start, end, moving_average, program):
    validate_series_options(metric, bucket, group_by, moving_average)
    if group_by is not None or metric == "volume-per-session":
        return _accumulated_series_data(
            user, metric, bucket, group_by, start, end, moving_average, program
        )

    if metric in {"sessions", "training-time", "volume-per-session"}:
        queryset = owned_sessions(user, start=start, end=end, program=program)
        rows = list(
            queryset.values(bucket_value=_bucket_expression(bucket))
            .annotate(
                sessions=Count("id"),
                volume=Sum("total_volume_kg"),
                duration=Sum("duration_min"),
            )
            .order_by()
        )
    else:
        queryset = owned_sets(user, start=start, end=end, program=program)
        rows = list(
            queryset.values(bucket_value=_bucket_expression(bucket, "session__session_date"))
            .annotate(volume=Sum("volume_kg"), sessions=Count("session_id", distinct=True))
            .order_by()
        )

    if not rows and (start is None or end is None):
        return {"bucket": bucket, "group_by": group_by, "count": 0, "items": []}

    if start is None or end is None:
        bounds = _series_bounds(user, start, end, program)
        effective_start = start if start is not None else bounds["first"]
        effective_end = end if end is not None else bounds["last"]
    else:
        effective_start = start
        effective_end = end
    validate_date_range(effective_start, effective_end)

    by_bucket = {row["bucket_value"]: row for row in rows}
    zero = Decimal(0) if metric in {"volume", "training-time"} else 0
    items = []
    values = []
    for current in iter_buckets(effective_start, effective_end, bucket):
        row = by_bucket.get(current)
        if metric == "sessions":
            value = row["sessions"] if row else 0
        elif metric == "training-time":
            value = Decimal(row["duration"] or 0) / Decimal(60) if row else zero
        elif metric == "volume-per-session":
            value = per_session(row["volume"], row["sessions"]) if row else zero
        else:
            value = row["volume"] if row else zero
        items.append(
            {
                "bucket_start": current.isoformat(),
                "value": round2(value),
                "groups": None,
            }
        )
        values.append(value)

    if moving_average:
        for index, item in enumerate(items):
            window = values[max(0, index - 3) : index + 1]
            item["value_4wma"] = round2(sum(window) / len(window)) if len(window) == 4 else None

    return {"bucket": bucket, "group_by": group_by, "count": len(items), "items": items}


def muscle_totals(user, start, end, program):
    mapping = muscle_map(user)
    exercise_rows = list(
        owned_sets(user, start=start, end=end, program=program)
        .values("exercise__name")
        .annotate(sets=Count("id"), volume=Sum("volume_kg"))
        .order_by()
    )
    totals = defaultdict(lambda: {"sessions": set(), "sets": 0, "volume": Decimal(0)})
    for row in exercise_rows:
        entry = totals[mapping.get(row["exercise__name"], "Other")]
        entry["sets"] += row["sets"]
        entry["volume"] += row["volume"] or Decimal(0)

    pair_rows = (
        owned_sets(user, start=start, end=end, program=program)
        .values("exercise__name", "session_id")
        .distinct()
    )
    for row in pair_rows:
        totals[mapping.get(row["exercise__name"], "Other")]["sessions"].add(row["session_id"])

    rows = [
        {
            "key": key,
            "sessions": len(entry["sessions"]),
            "sets": entry["sets"],
            "volume_kg": round2(entry["volume"]),
        }
        for key, entry in totals.items()
    ]
    rows.sort(key=lambda row: (-row["volume_kg"], row["key"]))
    return rows


def breakdown_data(user, dimension, start, end, limit, program):
    if dimension == "muscle":
        rows = muscle_totals(user, start, end, program)
        rows.sort(key=lambda row: (-row["volume_kg"], row["key"]))
        return {"count": len(rows), "items": rows[:limit]}

    if dimension in {"weekday", "program"}:
        buckets = defaultdict(lambda: {"sessions": 0, "sets": 0, "volume": Decimal(0)})
        if dimension == "weekday":
            for name in WEEKDAYS:
                buckets[name]
        for session in owned_sessions(user, start=start, end=end, program=program):
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
        buckets = defaultdict(lambda: {"session_ids": set(), "sets": 0, "volume": Decimal(0)})
        for row in owned_sets(user, start=start, end=end, program=program).values(
            "exercise__name", "session_id", "volume_kg"
        ):
            entry = buckets[row["exercise__name"]]
            entry["session_ids"].add(row["session_id"])
            entry["sets"] += 1
            entry["volume"] += row["volume_kg"]

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


PROGRESS_GROUP_BY = frozenset({"day", "session"})


def validate_progress_options(group_by):
    if group_by not in PROGRESS_GROUP_BY:
        raise ApiError(
            422,
            "validation_error",
            f"group_by={group_by} is not supported for exercise progress",
        )


def progress_data(user, name, start, end, group_by, program):
    validate_progress_options(group_by)
    grouped = defaultdict(list)
    for item in owned_sets(user, start=start, end=end, exercise=name, program=program):
        key = item.session_id if group_by == "session" else item.session.session_date
        grouped[key].append(item)

    ordered = sorted(
        grouped.items(),
        key=lambda entry: (entry[1][0].session.session_date, entry[0]),
    )
    items = []
    for key, entries in ordered:
        estimates = [item.est_1rm_kg for item in entries if item.est_1rm_kg is not None]
        weights = [item.weight_kg for item in entries if item.weight_kg is not None]
        items.append(
            {
                "date": entries[0].session.session_date.isoformat(),
                "session_id": key if group_by == "session" else None,
                "sets": len(entries),
                "best_est_1rm_kg": round2(max(estimates)) if estimates else None,
                "top_weight_kg": round2(max(weights)) if weights else None,
                "max_reps": max(item.reps for item in entries),
                "volume_kg": round2(sum((item.volume_kg for item in entries), Decimal(0))),
            }
        )
    return {"count": len(items), "items": items}


def exercise_record_data(user, name, start, end, program):
    by_reps = defaultdict(list)
    for item in owned_sets(user, start=start, end=end, exercise=name, program=program):
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
                "set_count": len(by_reps[reps]),
                "top_weight_kg": maybe_round2(best.weight_kg),
                "best_est_1rm_kg": maybe_round2(best.est_1rm_kg),
                "volume_kg": round2(best.volume_kg),
                "set_time": timestamp(best.set_time),
            }
        )
    return {"count": len(items), "items": items}


def _ranked_best_sets(user, start, end, program, kind):
    queryset = owned_sets(user, start=start, end=end, program=program)
    if kind == "strength":
        queryset = queryset.filter(est_1rm_kg__isnull=False)
        ordering = [
            F("est_1rm_kg").desc(),
            F("reps").desc(),
            F("weight_kg").desc(),
            F("set_time").desc(),
            F("set_order").asc(),
        ]
    else:
        queryset = queryset.filter(weight_kg__isnull=True)
        ordering = [F("reps").desc(), F("set_time").desc(), F("set_order").asc()]
    return (
        queryset.annotate(
            best_rank=Window(
                expression=RowNumber(),
                partition_by=[F("exercise_id")],
                order_by=ordering,
            )
        )
        .filter(best_rank=1)
        .values(
            "exercise__name",
            "est_1rm_kg",
            "reps",
            "weight_kg",
            "set_time",
            "seconds",
            "distance",
        )
        .order_by("set_time", "set_order")
    )


def est_1rm_record_data(user, start, end, program):
    items = [
        {
            "exercise": row["exercise__name"],
            "est_1rm_kg": round2(row["est_1rm_kg"]),
            "reps": row["reps"],
            "weight_kg": round2(row["weight_kg"]),
            "set_time": timestamp(row["set_time"]),
        }
        for row in _ranked_best_sets(user, start, end, program, "strength")
    ]
    items.sort(key=lambda row: -row["est_1rm_kg"])
    return {"count": len(items), "items": items}


def bodyweight_record_data(user, start, end, program):
    items = [
        {
            "exercise": row["exercise__name"],
            "reps": row["reps"],
            "set_time": timestamp(row["set_time"]),
            "seconds": maybe_round2(row["seconds"]),
            "distance": maybe_round2(row["distance"]),
        }
        for row in _ranked_best_sets(user, start, end, program, "bodyweight")
    ]
    items.sort(key=lambda row: -row["reps"])
    return {"count": len(items), "items": items}


PERSONAL_BEST_KINDS = ("strength", "bodyweight")


def personal_best_data(user, start, end, program, kind=None):
    kinds = [kind] if kind is not None else list(PERSONAL_BEST_KINDS)
    items = []
    for current_kind in kinds:
        current = list(_ranked_best_sets(user, start, end, program, current_kind))
        previous = {}
        if start is not None and start > date.min:
            previous = {
                row["exercise__name"]: row
                for row in _ranked_best_sets(
                    user, None, start - timedelta(days=1), program, current_kind
                )
            }
        for row in current:
            if current_kind == "strength":
                value = round2(row["est_1rm_kg"])
                prior_row = previous.get(row["exercise__name"])
                prior = round2(prior_row["est_1rm_kg"]) if prior_row else None
                weight_kg = round2(row["weight_kg"])
            else:
                value = row["reps"]
                prior_row = previous.get(row["exercise__name"])
                prior = prior_row["reps"] if prior_row else None
                weight_kg = None
            items.append(
                {
                    "exercise": row["exercise__name"],
                    "kind": current_kind,
                    "value": value,
                    "previous_value": prior,
                    "improvement": round2(value - prior) if prior is not None else None,
                    "is_personal_best": prior is not None and value > prior,
                    "reps": row["reps"],
                    "weight_kg": weight_kg,
                    "set_time": timestamp(row["set_time"]),
                }
            )
    kind_order = {name: index for index, name in enumerate(PERSONAL_BEST_KINDS)}
    items.sort(key=lambda row: (kind_order[row["kind"]], -row["value"], row["exercise"]))
    return {"count": len(items), "items": items}


def yearly_data(user, program):
    buckets = defaultdict(lambda: {"sessions": 0, "sets": 0, "volume": Decimal(0), "duration": 0})
    for session in owned_sessions(user, program=program):
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


def _session_rows(user, *, end=None, program=None):
    return owned_sessions(user, end=end, program=program).values(
        "session_date", "set_count", "total_volume_kg", "duration_min"
    )


def _roll_up(rows):
    years = defaultdict(lambda: {"sessions": 0, "sets": 0, "volume": Decimal(0), "duration": 0})
    for row in rows:
        entry = years[row["session_date"].year]
        entry["sessions"] += 1
        entry["sets"] += row["set_count"]
        entry["volume"] += row["total_volume_kg"]
        entry["duration"] += row["duration_min"] or 0
    return years


def _year_totals(entry):
    if entry is None:
        return {"sessions": 0, "sets": 0, "volume_kg": 0.0, "hours": 0.0}
    return {
        "sessions": entry["sessions"],
        "sets": entry["sets"],
        "volume_kg": float(entry["volume"]),
        "hours": entry["duration"] / 60,
    }


def pace_data(user, year, as_of, program):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    previous = year - 1
    cutoff = _cutoff(year, as_of)
    last_cutoff = _cutoff(previous, as_of)

    with transaction.atomic():
        rows = list(_session_rows(user, end=cutoff, program=program))

    years = _roll_up(rows)
    ytd = _year_totals(years.get(year))
    last_year_rows = [
        row
        for row in rows
        if row["session_date"].year == previous and row["session_date"] <= last_cutoff
    ]
    last_ytd = _year_totals(_roll_up(last_year_rows).get(previous))
    last_full = _year_totals(years.get(previous))

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
    for row_year in sorted(years):
        entry = _year_totals(years[row_year])
        cumulative_sessions += entry["sessions"]
        cumulative_volume += entry["volume_kg"]
        pace.append(
            {
                "year": row_year,
                "sessions": entry["sessions"],
                "volume_kg": round2(entry["volume_kg"]),
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


def _year_bounds(included, year, cutoff):
    bounds = Q()
    for value in included:
        bounds |= Q(
            session_date__gte=date(value, 1, 1),
            session_date__lte=cutoff if value == year else date(value, 12, 31),
        )
    return bounds


def curve_data(user, year, years, as_of, program):
    cutoff = _cutoff(year, as_of)
    with transaction.atomic():
        rows = list(
            owned_sessions(user, program=program)
            .filter(_year_bounds(years, year, cutoff))
            .values("session_date")
            .annotate(sessions=Count("id"), volume=Sum("total_volume_kg"))
            .order_by()
        )
    daily = {row["session_date"]: row for row in rows}

    items = []
    for included in years:
        first = date(included, 1, 1)
        final = cutoff if included == year else date(included, 12, 31)
        cumulative_sessions = 0
        cumulative_volume = Decimal(0)
        current = first
        while True:
            entry = daily.get(current)
            if entry:
                cumulative_sessions += entry["sessions"]
                cumulative_volume += entry["volume"] or Decimal(0)
            items.append(
                {
                    "year": included,
                    "date": current.isoformat(),
                    "day_of_year": (current - first).days + 1,
                    "sessions": entry["sessions"] if entry else 0,
                    "cumulative_sessions": cumulative_sessions,
                    "cumulative_volume_kg": round2(cumulative_volume),
                }
            )
            if current >= final:
                break
            current += timedelta(days=1)

    return {"year": year, "years": years, "count": len(items), "items": items}


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
