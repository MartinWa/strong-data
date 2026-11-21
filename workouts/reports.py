import calendar
import math
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.db.models import Max, Min
from django.urls import reverse
from django.utils import timezone

from api.contract import MAX_RANGE_DAYS
from api.queries import (
    breakdown_data,
    curve_data,
    exercise_record_data,
    iter_buckets,
    muscle_totals,
    pace_data,
    personal_best_data,
    progress_data,
    series_data,
    summary_data,
    yearly_data,
)

from .models import Exercise, WorkoutSession

RANGE_KEYS = ("4w", "12w", "6m", "1y", "all")
DEFAULT_RANGE = "12w"
RANGE_LABELS = {
    "4w": "4 weeks",
    "12w": "12 weeks",
    "6m": "6 months",
    "1y": "1 year",
    "all": "All time",
}
METRIC_KEYS = ("volume", "sessions", "time")
DEFAULT_METRIC = "volume"
METRIC_SERIES = {
    "volume": "volume",
    "sessions": "sessions",
    "time": "training-time",
}
METRIC_LABELS = {
    "volume": "Volume",
    "sessions": "Sessions",
    "time": "Hours",
}
METRIC_UNITS = {
    "volume": "t",
    "sessions": "",
    "time": "h",
}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
BUCKET_NOUNS = {"day": "day", "week": "week", "month": "month", "year": "year"}
HEATMAP_DAYS = 364
MAX_BARS = 7
CHART_WIDTH = 720
CHART_HEIGHT = 240
CHART_LEFT = 54
CHART_RIGHT = 14
CHART_TOP = 14
CHART_BOTTOM = 34


def _get(params, key):
    value = params.get(key, "") if params is not None else ""
    return "" if value is None else str(value).strip()


def parse_report_params(params):
    range_key = _get(params, "range")
    if range_key not in RANGE_KEYS:
        range_key = DEFAULT_RANGE
    metric = _get(params, "metric")
    if metric not in METRIC_KEYS:
        metric = DEFAULT_METRIC
    program = _get(params, "program")
    raw_year = _get(params, "year")
    year = None
    if raw_year.isascii() and raw_year.isdigit() and len(raw_year) <= 4:
        year = int(raw_year)
    return {"range": range_key, "metric": metric, "program": program, "year": year}


def filtered_url(path, params):
    query = {"range": params["range"], "metric": params["metric"]}
    if params["program"]:
        query["program"] = params["program"]
    if params["year"] is not None:
        query["year"] = str(params["year"])
    return path + "?" + urlencode(query)


def local_datetime(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return timezone.localtime(parsed)


def shift_months(value, months):
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def shift_years(value, years):
    year = value.year + years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return date(year, value.month, day)


def period_label(start, end):
    if start is None:
        return RANGE_LABELS["all"]
    left = f"{start.day} {MONTHS[start.month - 1]}"
    right = f"{end.day} {MONTHS[end.month - 1]}"
    if start.year == end.year:
        return f"{left} – {right} {end.year}"
    return f"{left} {start.year} – {right} {end.year}"


def short_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def bucket_end(current, bucket):
    if bucket == "day":
        return current
    if bucket == "week":
        return current + timedelta(days=6)
    if bucket == "month":
        return shift_months(current, 1) - timedelta(days=1)
    return date(current.year, 12, 31)


def partial_buckets(start, end, bucket):
    info = {}
    for current in iter_buckets(start, end, bucket):
        final = bucket_end(current, bucket)
        clipped_start = max(current, start)
        clipped_end = min(final, end)
        days = max(0, (clipped_end - clipped_start).days + 1)
        total = (final - current).days + 1
        in_progress = final > end >= current
        partial = days < total
        if in_progress:
            note = "in progress"
        elif partial:
            note = f"partial {BUCKET_NOUNS[bucket]}, {days} of {total} days"
        else:
            note = ""
        info[current] = {
            "partial": partial,
            "in_progress": in_progress,
            "days": days,
            "total": total,
            "note": note,
        }
    return info


def resolve_range(key, today, earliest):
    if key not in RANGE_KEYS:
        key = DEFAULT_RANGE
    previous = None
    if key == "all":
        start = earliest.replace(day=1) if earliest else None
        end = today
        bucket = "month"
    else:
        end = today
        if key == "4w":
            start = today - timedelta(days=27)
            bucket = "week"
        elif key == "12w":
            start = today - timedelta(days=83)
            bucket = "week"
        elif key == "6m":
            start = shift_months(today, -6) + timedelta(days=1)
            bucket = "week"
        else:
            start = shift_years(today, -1) + timedelta(days=1)
            bucket = "month"
        span = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        previous = {
            "start": previous_end - timedelta(days=span - 1),
            "end": previous_end,
        }
    return {
        "key": key,
        "start": start,
        "end": end,
        "bucket": bucket,
        "previous": previous,
        "label": period_label(start, end),
        "partial": partial_buckets(start, end, bucket) if start else {},
    }


def session_span(user, program=None):
    queryset = WorkoutSession.objects.filter(owner=user)
    if program:
        queryset = queryset.filter(program=program)
    return queryset.aggregate(first=Min("session_date"), last=Max("session_date"))


def session_dates(user, start, end, program=None):
    queryset = WorkoutSession.objects.filter(owner=user)
    if start is not None:
        queryset = queryset.filter(session_date__gte=start)
    if end is not None:
        queryset = queryset.filter(session_date__lte=end)
    if program:
        queryset = queryset.filter(program=program)
    return list(queryset.order_by("session_date").values_list("session_date", flat=True).distinct())


def training_streaks(dates, today):
    ordered = sorted(set(dates))
    longest = 0
    run = 0
    previous = None
    for current in ordered:
        run = run + 1 if previous is not None and current == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = current
    last = ordered[-1] if ordered else None
    current_streak = run if last is not None and (today - last).days <= 1 else None
    return {"longest": longest, "current": current_streak, "last": last, "days": len(ordered)}


def series_for_range(user, metric, bucket, start, end, moving_average, program):
    if start is None or (end - start).days <= MAX_RANGE_DAYS:
        return series_data(user, metric, bucket, None, start, end, moving_average, program)
    if bucket not in {"month", "year"}:
        return series_data(user, metric, bucket, None, start, end, False, program)
    items = []
    for year in range(start.year, end.year + 1):
        chunk_start = max(start, date(year, 1, 1))
        chunk_end = min(end, date(year, 12, 31))
        chunk = series_data(user, metric, bucket, None, chunk_start, chunk_end, False, program)
        items.extend(chunk["items"])
    return {"bucket": bucket, "group_by": None, "count": len(items), "items": items}


def nice_max(value):
    if value is None or not math.isfinite(float(value)) or value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    for multiplier in (1, 2, 4, 5, 10):
        candidate = multiplier * (10**exponent)
        if candidate >= value:
            return float(candidate)
    return float(10 ** (exponent + 1))


def _round_coord(value):
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), 2)


def _tick_label(value, unit):
    text = str(int(value)) if value == int(value) else f"{value:g}"
    return f"{text}{unit}" if unit else text


def axis_ticks(maximum, unit=""):
    return [
        {"value": 0, "label": _tick_label(0, unit)},
        {"value": maximum / 2, "label": _tick_label(maximum / 2, unit)},
        {"value": maximum, "label": _tick_label(maximum, unit)},
    ]


def _full_bucket_label(value, bucket):
    if bucket == "day":
        return short_date(value)
    if bucket == "week":
        return f"Week of {value.day} {MONTHS[value.month - 1]} {value.year}"
    if bucket == "month":
        return f"{MONTHS[value.month - 1]} {value.year}"
    return str(value.year)


def _tick_bucket_label(value, bucket, multi_year):
    if bucket == "day":
        return f"{value.day} {MONTHS[value.month - 1]}"
    if bucket == "week":
        return f"{value.day} {MONTHS[value.month - 1]}"
    if bucket == "month":
        if multi_year and value.month == 1:
            return str(value.year)
        return MONTHS[value.month - 1]
    return str(value.year)


def thin_indexes(count, maximum=MAX_BARS):
    if count <= maximum:
        return list(range(count))
    indexes = []
    for step in range(maximum):
        index = round(step * (count - 1) / (maximum - 1))
        if index not in indexes:
            indexes.append(index)
    return indexes


def _plot_frame():
    plot_width = CHART_WIDTH - CHART_LEFT - CHART_RIGHT
    plot_height = CHART_HEIGHT - CHART_TOP - CHART_BOTTOM
    return plot_width, plot_height


def bar_chart(points, *, unit="", bucket="week", multi_year=False, value_text=None, aria_label=""):
    plot_width, plot_height = _plot_frame()
    maximum = nice_max(max((point["value"] for point in points), default=0))
    ticks = axis_ticks(maximum, unit)
    count = len(points)
    slot = plot_width / count if count else plot_width
    bar_width = max(3.0, slot * 0.62)
    bars = []
    ma_points = []
    for index, point in enumerate(points):
        value = point["value"]
        height = plot_height * (value / maximum) if maximum else 0
        x = CHART_LEFT + slot * index + (slot - bar_width) / 2
        y = CHART_TOP + plot_height - height
        label = _full_bucket_label(point["date"], bucket)
        text = value_text(point) if value_text else _tick_label(value, unit)
        title = f"{label}: {text}"
        if point.get("note"):
            title = f"{title}, {point['note']}"
        bars.append(
            {
                "x": _round_coord(x),
                "y": _round_coord(y),
                "width": _round_coord(bar_width),
                "height": _round_coord(height),
                "title": title,
                "partial": point.get("partial", False),
                "in_progress": point.get("in_progress", False),
                "index": index,
            }
        )
        if point.get("moving_average") is not None:
            ma_value = point["moving_average"]
            ma_y = CHART_TOP + plot_height - plot_height * (ma_value / maximum)
            ma_points.append(
                f"{_round_coord(CHART_LEFT + slot * index + slot / 2)},{_round_coord(ma_y)}"
            )
    indexes = thin_indexes(count)
    xlabels = [
        {
            "x": _round_coord(CHART_LEFT + slot * index + slot / 2),
            "label": _tick_bucket_label(points[index]["date"], bucket, multi_year),
        }
        for index in indexes
    ]
    tick_positions = [
        {"y": _round_coord(CHART_TOP + plot_height), "label": ticks[0]["label"]},
        {
            "y": _round_coord(CHART_TOP + plot_height / 2),
            "label": ticks[1]["label"],
        },
        {"y": _round_coord(CHART_TOP), "label": ticks[2]["label"]},
    ]
    return {
        "kind": "bars",
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "left": CHART_LEFT,
        "right": CHART_RIGHT,
        "top": CHART_TOP,
        "bottom": CHART_BOTTOM,
        "plot_bottom": _round_coord(CHART_TOP + plot_height),
        "right_edge": CHART_WIDTH - CHART_RIGHT,
        "bars": bars,
        "line": " ".join(ma_points),
        "has_line": len(ma_points) >= 2,
        "xlabels": xlabels,
        "ticks": tick_positions,
        "aria_label": aria_label,
        "empty": maximum <= 1.0 and all(point["value"] == 0 for point in points),
    }


def line_chart(lines, *, x_max, x_ticks, y_unit="", aria_label=""):
    plot_width, plot_height = _plot_frame()
    values = [value for line in lines for _, value in line["points"]]
    maximum = nice_max(max(values, default=0))
    x_max = x_max if x_max > 0 else 1

    def project(x_value, y_value):
        x = CHART_LEFT + plot_width * (x_value / x_max)
        y = CHART_TOP + plot_height - plot_height * (y_value / maximum)
        return f"{_round_coord(x)},{_round_coord(y)}"

    drawn = []
    for index, line in enumerate(lines):
        if not line["points"]:
            continue
        projected = [project(x, y) for x, y in line["points"]]
        dots = []
        if len(projected) == 1:
            x, y = projected[0].split(",")
            dots.append({"x": x, "y": y})
        drawn.append(
            {
                "label": line["label"],
                "class": f"series-{index + 1}",
                "points": " ".join(projected),
                "dots": dots,
            }
        )
    tick_positions = [
        {"y": _round_coord(CHART_TOP + plot_height), "label": _tick_label(0, y_unit)},
        {
            "y": _round_coord(CHART_TOP + plot_height / 2),
            "label": _tick_label(maximum / 2, y_unit),
        },
        {"y": _round_coord(CHART_TOP), "label": _tick_label(maximum, y_unit)},
    ]
    xlabels = [
        {
            "x": _round_coord(CHART_LEFT + plot_width * (position / x_max)),
            "label": label,
        }
        for position, label in x_ticks
    ]
    return {
        "kind": "lines",
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "left": CHART_LEFT,
        "right": CHART_RIGHT,
        "top": CHART_TOP,
        "bottom": CHART_BOTTOM,
        "plot_bottom": _round_coord(CHART_TOP + plot_height),
        "right_edge": CHART_WIDTH - CHART_RIGHT,
        "lines": drawn,
        "xlabels": xlabels,
        "ticks": tick_positions,
        "aria_label": aria_label,
        "empty": maximum <= 1.0 and all(value == 0 for value in values),
    }


def delta(current, previous, *, absolute=False, suffix="", comparison=""):
    if previous is None:
        return None
    if absolute:
        change = current - previous
        if change > 0:
            text = f"+{change:.1f}{suffix}"
            direction = "up"
        elif change < 0:
            text = f"−{abs(change):.1f}{suffix}"
            direction = "down"
        else:
            text = "—"
            direction = "flat"
        spoken = (
            f"up {abs(change):.1f}{suffix}"
            if change > 0
            else f"down {abs(change):.1f}{suffix}"
            if change < 0
            else "unchanged"
        )
        return {"text": text, "class": direction, "aria": f"{spoken} versus {comparison}"}
    if previous == 0:
        return {
            "text": "—",
            "class": "flat",
            "aria": f"no value in {comparison} to compare",
        }
    change = (current - previous) / previous * 100
    percent = round(abs(change))
    if change > 0:
        text = f"↑ {percent}%"
        direction = "up"
        spoken = f"up {percent} percent"
    elif change < 0:
        text = f"↓ {percent}%"
        direction = "down"
        spoken = f"down {percent} percent"
    else:
        text = "—"
        direction = "flat"
        spoken = "unchanged"
    return {"text": text, "class": direction, "aria": f"{spoken} versus {comparison}"}


def format_tonnes(kg):
    return f"{float(kg) / 1000:.1f} t"


def format_hours(hours):
    return f"{float(hours):.1f} h"


def format_kg(kg):
    return f"{float(kg):.1f} kg"


def format_int(value):
    return str(int(value))


def _last_session_text(last, today):
    if last is None:
        return "no sessions yet"
    days = (today - last).days
    if days <= 0:
        return "last session today"
    if days == 1:
        return "last session yesterday"
    return f"last session {days} days ago"


def _kpi_cards(summary, previous, comparison):
    cards = [
        {
            "key": "sessions",
            "label": "Sessions",
            "value": format_int(summary["sessions"]),
            "delta": delta(
                summary["sessions"],
                previous["sessions"] if previous else None,
                comparison=comparison,
            ),
        },
        {
            "key": "volume",
            "label": "Volume",
            "value": format_tonnes(summary["volume_kg"]),
            "delta": delta(
                summary["volume_kg"],
                previous["volume_kg"] if previous else None,
                comparison=comparison,
            ),
        },
        {
            "key": "hours",
            "label": "Training time",
            "value": format_hours(summary["hours"]),
            "delta": delta(
                summary["hours"],
                previous["hours"] if previous else None,
                comparison=comparison,
            ),
        },
        {
            "key": "sets",
            "label": "Sets",
            "value": format_int(summary["sets"]),
            "delta": delta(
                summary["sets"],
                previous["sets"] if previous else None,
                comparison=comparison,
            ),
        },
        {
            "key": "per-week",
            "label": "Per week",
            "value": f"{summary['sessions_per_week']:.1f}",
            "delta": delta(
                summary["sessions_per_week"],
                previous["sessions_per_week"] if previous else None,
                absolute=True,
                suffix="/wk",
                comparison=comparison,
            ),
        },
    ]
    return cards


def _training_load(user, resolved, metric, program):
    series_metric = METRIC_SERIES[metric]
    bucket = resolved["bucket"]
    start = resolved["start"]
    end = resolved["end"]
    bucket_count = len(list(iter_buckets(start, end, bucket)))
    moving_average = bucket == "week" and bucket_count >= 8
    series = series_for_range(user, series_metric, bucket, start, end, moving_average, program)
    partial = resolved["partial"]
    multi_year = start.year != end.year
    points = []
    rows = []
    for item in series["items"]:
        bucket_date = date.fromisoformat(item["bucket_start"])
        info = partial.get(bucket_date, {})
        raw = item["value"]
        display = raw / 1000 if metric == "volume" else raw
        moving = item.get("value_4wma")
        display_moving = moving / 1000 if metric == "volume" and moving is not None else moving
        points.append(
            {
                "date": bucket_date,
                "value": display,
                "moving_average": display_moving,
                "partial": info.get("partial", False),
                "in_progress": info.get("in_progress", False),
                "note": info.get("note", ""),
            }
        )
        if metric == "volume":
            text = format_tonnes(raw)
        elif metric == "time":
            text = format_hours(raw)
        else:
            text = format_int(raw)
        rows.append(
            {
                "date": _full_bucket_label(bucket_date, bucket),
                "text": text,
                "note": info.get("note", ""),
            }
        )

    def value_text(point):
        if metric == "volume":
            return format_tonnes(point["value"] * 1000)
        if metric == "time":
            return format_hours(point["value"])
        return format_int(point["value"])

    chart = bar_chart(
        points,
        unit=METRIC_UNITS[metric],
        bucket=bucket,
        multi_year=multi_year,
        value_text=value_text,
        aria_label=(f"{METRIC_LABELS[metric]} per {BUCKET_NOUNS[bucket]} from {resolved['label']}"),
    )
    return {
        "metric": metric,
        "chart": chart,
        "rows": rows,
        "has_moving_average": moving_average and chart["has_line"],
        "empty": chart["empty"],
        "empty_text": (
            "No volume in this period." if metric == "volume" else "No training in this period."
        ),
    }


def muscle_totals_card(user, start, end, program):
    rows = muscle_totals(user, start, end, program)
    rows.sort(key=lambda row: (-row["sets"], row["key"]))
    total_sets = sum(row["sets"] for row in rows)
    displayed = rows[:8]
    tail = rows[8:]
    folded = 0
    if tail:
        folded = len(tail)
        tail_sets = sum(row["sets"] for row in tail)
        tail_volume = sum(row["volume_kg"] for row in tail)
        existing = next((row for row in displayed if row["key"] == "Other"), None)
        if existing is not None:
            existing["sets"] += tail_sets
            existing["volume_kg"] = round(existing["volume_kg"] + tail_volume, 2)
            existing["folded"] = folded
        else:
            displayed = displayed + [
                {
                    "key": "Other",
                    "sets": tail_sets,
                    "volume_kg": round(tail_volume, 2),
                    "sessions": None,
                    "folded": folded,
                }
            ]
    items = []
    for row in displayed:
        share = round(row["sets"] / total_sets * 100) if total_sets else 0
        items.append(
            {
                "key": row["key"],
                "sets": row["sets"],
                "volume": format_tonnes(row["volume_kg"]),
                "share": share,
                "folded": row.get("folded", 0),
            }
        )
    return {"items": items, "total_sets": total_sets}


def _consistency_card(user, start, end, today, program):
    dates = session_dates(user, start, end, program)
    streaks = training_streaks(dates, today)

    heat_start = max(start, end - timedelta(days=HEATMAP_DAYS))
    grid_start = heat_start - timedelta(days=heat_start.weekday())
    grid_end = end + timedelta(days=6 - end.weekday())
    day_rows = series_data(user, "sessions", "day", None, heat_start, end, False, program)["items"]
    counts = {date.fromisoformat(item["bucket_start"]): int(item["value"]) for item in day_rows}
    weeks = []
    month_label = None
    last_label_column = None
    current = grid_start
    while current <= grid_end:
        column = (current - grid_start).days // 7
        cells = []
        for offset in range(7):
            day = current + timedelta(days=offset)
            active = heat_start <= day <= end
            count = counts.get(day, 0) if active else None
            level = (
                None
                if not active
                else 0
                if count == 0
                else 1
                if count == 1
                else 2
                if count < 3
                else 3
            )
            if not active:
                title = ""
            elif count == 0:
                title = f"{short_date(day)}: no training"
            else:
                title = f"{short_date(day)}: {count} session{'s' if count != 1 else ''}"
            cells.append(
                {
                    "date": day,
                    "level": level,
                    "count": count,
                    "title": title,
                    "label": short_date(day),
                }
            )
        week_label = ""
        first = cells[0]
        if first["date"] >= heat_start:
            this_month = MONTHS[first["date"].month - 1]
            if this_month != month_label:
                month_label = this_month
                if last_label_column is None or column - last_label_column >= 4:
                    last_label_column = column
                    week_label = this_month
        weeks.append({"cells": cells, "label": week_label})
        current += timedelta(days=7)

    heat_rows = [
        {
            "date": short_date(day),
            "weekday": WEEKDAYS[day.weekday()],
            "sessions": counts[day],
        }
        for day in sorted(counts)
        if counts[day] > 0
    ]

    weekday_rows = breakdown_data(user, "weekday", start, end, 7, program)["items"]
    busiest = max((row["sessions"] for row in weekday_rows), default=0)
    weekday_items = []
    for row in weekday_rows:
        weekday_items.append(
            {
                "key": row["key"][:3],
                "sessions": row["sessions"],
                "sets": row["sets"],
                "volume": format_tonnes(row["volume_kg"]),
                "width": round(row["sessions"] / busiest * 100) if busiest else 0,
                "accent": busiest > 0 and row["sessions"] == busiest,
            }
        )

    return {
        "weeks": weeks,
        "has_heatmap": bool(dates),
        "heat_rows": heat_rows,
        "streaks": streaks,
        "weekdays": weekday_items,
        "busiest": busiest,
    }


def _best_lifts(user, start, end, program, kind, params):
    rows = personal_best_data(user, start, end, program, kind)["items"][:6]
    items = []
    for row in rows:
        set_date = local_datetime(row["set_time"]).date()
        if kind == "strength":
            value = format_kg(row["value"])
            detail = (
                f"{row['weight_kg']:g} kg × {row['reps']} · "
                f"{set_date.day} {MONTHS[set_date.month - 1]}"
            )
        else:
            value = f"{row['value']} reps"
            detail = f"{set_date.day} {MONTHS[set_date.month - 1]}"
        if row["is_personal_best"]:
            badge = {"text": "NEW PR", "class": "badge-success"}
        elif row["previous_value"] is None:
            badge = {"text": "First recorded", "class": "badge"}
        else:
            badge = None
        items.append(
            {
                "exercise": row["exercise"],
                "value": value,
                "detail": detail,
                "badge": badge,
                "url": filtered_url(
                    reverse("report_exercise", kwargs={"name": row["exercise"]}), params
                ),
            }
        )
    return {"kind": kind, "items": items}


def _month_tick_positions(year):
    return [
        (date(year, month, 1).timetuple().tm_yday, MONTHS[month - 1]) for month in range(1, 13, 3)
    ]


def _yearly_card(user, today, program, requested_year):
    yearly = yearly_data(user, program)
    years = [item["year"] for item in yearly["items"]]
    by_year = {item["year"]: item for item in yearly["items"]}
    if requested_year is not None and requested_year in years:
        focus = requested_year
    elif today.year in years:
        focus = today.year
    elif years:
        focus = max(years)
    else:
        focus = today.year

    drawn = [year for year in sorted(years, reverse=True) if year <= focus][:3]
    as_of = today if focus == today.year else date(focus, 12, 31)
    curve = curve_data(user, focus, sorted(drawn), as_of, program) if drawn else {"items": []}

    grouped = {year: [] for year in sorted(drawn)}
    for item in curve["items"]:
        grouped.setdefault(item["year"], []).append(item)

    lines = []
    for year in sorted(drawn, reverse=True):
        points = [
            (item["day_of_year"], item["cumulative_volume_kg"] / 1000) for item in grouped[year]
        ]
        lines.append({"label": str(year), "points": points})
    chart = line_chart(
        lines,
        x_max=366,
        x_ticks=_month_tick_positions(focus),
        y_unit=" t",
        aria_label=(
            "Cumulative volume for " + ", ".join(str(year) for year in sorted(drawn, reverse=True))
            if drawn
            else "Cumulative volume"
        ),
    )

    totals_rows = [
        {
            "year": year,
            "sessions": by_year[year]["sessions"],
            "sets": by_year[year]["sets"],
            "volume": format_tonnes(by_year[year]["volume_kg"]),
            "hours": format_hours(by_year[year]["hours"]),
        }
        for year in sorted(drawn, reverse=True)
    ]

    month_rows = []
    if drawn:
        for month in range(1, 13):
            cells = []
            for year in sorted(drawn, reverse=True):
                items = grouped.get(year, [])
                month_items = [
                    item for item in items if date.fromisoformat(item["date"]).month == month
                ]
                cells.append(
                    {
                        "year": year,
                        "value": (
                            format_tonnes(month_items[-1]["cumulative_volume_kg"])
                            if month_items
                            else "—"
                        ),
                    }
                )
            month_rows.append({"month": MONTHS[month - 1], "cells": cells})

    footer = None
    if focus == today.year:
        pace = pace_data(user, focus, today, program)
        elapsed_days = (today - date(focus, 1, 1)).days + 1
        can_project = elapsed_days >= 28
        footer = {
            "kind": "current",
            "ytd": format_tonnes(pace["ytd"]["volume_kg"]),
            "last_year": format_tonnes(pace["last_year_to_date"]["volume_kg"]),
            "can_project": can_project,
            "projected": format_tonnes(pace["projected"]["volume_kg"]) if can_project else None,
            "needed_per_week": (
                format_tonnes(pace["needed_per_week"]["volume_kg"]) + "/wk" if can_project else None
            ),
        }
    elif focus in by_year:
        current = by_year[focus]
        previous = by_year.get(focus - 1)
        footer = {
            "kind": "past",
            "volume": format_tonnes(current["volume_kg"]),
            "sessions": current["sessions"],
            "delta": (
                delta(
                    current["volume_kg"],
                    previous["volume_kg"],
                    comparison=f"the previous full year ({focus - 1})",
                )
                if previous
                else None
            ),
        }

    return {
        "years": years,
        "year_links": [
            {"year": year, "current": year == focus} for year in sorted(years, reverse=True)
        ],
        "focus": focus,
        "drawn": sorted(drawn, reverse=True),
        "has_data": bool(drawn),
        "chart": chart,
        "totals_rows": totals_rows,
        "month_rows": month_rows,
        "month_years": sorted(drawn, reverse=True),
        "footer": footer,
    }


def build_report(user, params, today):
    parsed = parse_report_params(params)
    program = parsed["program"] or None
    owned = WorkoutSession.objects.filter(owner=user)
    has_data = owned.exists()
    programs = list(owned.values_list("program", flat=True).distinct().order_by("program"))
    context = {
        "has_data": has_data,
        "programs": programs,
        "selected_program": parsed["program"],
        "range_key": parsed["range"],
        "metric": parsed["metric"],
        "requested_year": parsed["year"],
        "range_options": [
            {"key": key, "label": RANGE_LABELS[key], "current": key == parsed["range"]}
            for key in RANGE_KEYS
        ],
        "metric_options": [
            {"key": key, "label": METRIC_LABELS[key], "current": key == parsed["metric"]}
            for key in METRIC_KEYS
        ],
    }
    if not has_data:
        return context

    span = session_span(user, program)
    resolved = resolve_range(parsed["range"], today, span["first"])
    context.update(
        {
            "range": resolved,
            "period_label": resolved["label"],
            "last_session_text": _last_session_text(span["last"], today),
        }
    )

    start = resolved["start"]
    end = resolved["end"]
    previous_window = resolved["previous"]
    summary = summary_data(user, start, end, program)
    previous = (
        summary_data(user, previous_window["start"], previous_window["end"], program)
        if previous_window
        else None
    )
    comparison = (
        f"the previous {RANGE_LABELS[resolved['key']]}"
        if previous_window
        else "the previous period"
    )
    context.update(
        {
            "summary": summary,
            "previous": previous,
            "comparison": comparison,
            "kpis": _kpi_cards(summary, previous, comparison),
            "range_empty": summary["sessions"] == 0,
        }
    )
    if summary["sessions"] == 0:
        return context

    context["training_load"] = _training_load(user, resolved, parsed["metric"], program)
    context["muscle"] = muscle_totals_card(user, start, end, program)
    context["consistency"] = _consistency_card(user, start, end, today, program)
    context["best_lifts"] = {
        "strength": _best_lifts(user, start, end, program, "strength", parsed),
        "bodyweight": _best_lifts(user, start, end, program, "bodyweight", parsed),
    }
    context["yearly"] = _yearly_card(user, today, program, parsed["year"])
    return context


def build_exercise_report(user, name, params, today):
    parsed = parse_report_params(params)
    program = parsed["program"] or None
    if not Exercise.objects.filter(owner=user, name=name).exists():
        return None
    owned = WorkoutSession.objects.filter(owner=user)
    programs = list(owned.values_list("program", flat=True).distinct().order_by("program"))
    span = session_span(user, program)
    resolved = resolve_range(parsed["range"], today, span["first"])
    start = resolved["start"]
    end = resolved["end"]
    items = progress_data(user, name, start, end, "session", program)["items"]
    records = exercise_record_data(user, name, start, end, program)["items"]

    uses_1rm = any(item["best_est_1rm_kg"] is not None for item in items)
    value_key = "best_est_1rm_kg" if uses_1rm else "max_reps"
    unit = " kg" if uses_1rm else " reps"
    points = [
        (index, item[value_key]) for index, item in enumerate(items) if item[value_key] is not None
    ]
    indexes = thin_indexes(len(items), maximum=7)
    x_ticks = []
    for index in indexes:
        item_date = date.fromisoformat(items[index]["date"])
        x_ticks.append((index, f"{item_date.day} {MONTHS[item_date.month - 1]}"))
    chart = line_chart(
        [{"label": name, "points": points}],
        x_max=max(len(items) - 1, 1),
        x_ticks=x_ticks,
        y_unit=unit,
        aria_label=(
            f"{'Estimated 1RM' if uses_1rm else 'Max reps'} for {name} from {resolved['label']}"
        ),
    )
    table_rows = [
        {
            "date": short_date(date.fromisoformat(item["date"])),
            "sets": item["sets"],
            "estimate": format_kg(item["best_est_1rm_kg"])
            if item["best_est_1rm_kg"] is not None
            else "—",
            "top_weight": format_kg(item["top_weight_kg"])
            if item["top_weight_kg"] is not None
            else "—",
            "reps": item["max_reps"],
            "volume": format_tonnes(item["volume_kg"]),
        }
        for item in items
    ]
    record_rows = [
        {
            "reps": row["reps"],
            "set_count": row["set_count"],
            "top_weight": format_kg(row["top_weight_kg"])
            if row["top_weight_kg"] is not None
            else "—",
            "estimate": format_kg(row["best_est_1rm_kg"])
            if row["best_est_1rm_kg"] is not None
            else "—",
            "volume": format_kg(row["volume_kg"]),
            "set_time": local_datetime(row["set_time"]),
        }
        for row in records
    ]
    return {
        "has_data": True,
        "exercise": name,
        "programs": programs,
        "selected_program": parsed["program"],
        "range_key": parsed["range"],
        "range": resolved,
        "period_label": resolved["label"],
        "metric": parsed["metric"],
        "requested_year": parsed["year"],
        "reports_url": filtered_url(reverse("reports"), parsed),
        "range_options": [
            {"key": key, "label": RANGE_LABELS[key], "current": key == parsed["range"]}
            for key in RANGE_KEYS
        ],
        "metric_label": "Estimated 1RM" if uses_1rm else "Max reps",
        "chart": chart,
        "has_points": bool(items),
        "table_rows": table_rows,
        "record_rows": record_rows,
    }
