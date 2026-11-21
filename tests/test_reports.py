from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from api.contract import MAX_RANGE_DAYS
from api.queries import summary_data
from workouts.models import Exercise, ExerciseMeta, WorkoutSession, WorkoutSet
from workouts.reports import (
    METRIC_SERIES,
    axis_ticks,
    bar_chart,
    delta,
    line_chart,
    muscle_totals_card,
    nice_max,
    partial_buckets,
    resolve_range,
    series_for_range,
    session_dates,
    session_span,
    shift_months,
    shift_years,
    training_streaks,
)

TODAY = date(2026, 8, 31)


def test_unknown_range_and_metric_fall_back_to_defaults():
    resolved = resolve_range("nope", TODAY, date(2024, 1, 15))
    assert resolved["key"] == "12w"
    assert resolved["bucket"] == "week"
    assert resolved["start"] == TODAY - timedelta(days=83)
    assert resolved["end"] == TODAY


def test_week_ranges_have_equal_previous_windows():
    for key, days in (("4w", 28), ("12w", 84)):
        resolved = resolve_range(key, TODAY, None)
        assert (resolved["end"] - resolved["start"]).days + 1 == days
        previous = resolved["previous"]
        assert previous["end"] == resolved["start"] - timedelta(days=1)
        assert (previous["end"] - previous["start"]).days + 1 == days


def test_six_month_range_clamps_month_ends_and_shifts_one_day():
    resolved = resolve_range("6m", TODAY, None)
    assert resolved["start"] == date(2026, 3, 1)
    assert resolved["bucket"] == "week"

    february_end = resolve_range("6m", date(2026, 8, 29), None)
    assert february_end["start"] == date(2026, 3, 1)

    clamped = resolve_range("6m", date(2026, 8, 31), None)
    assert clamped["start"] == date(2026, 3, 1)
    assert shift_months(date(2026, 8, 31), -6) == date(2026, 2, 28)


def test_year_range_clamps_leap_day_and_uses_months():
    resolved = resolve_range("1y", date(2028, 2, 29), None)
    assert resolved["start"] == date(2027, 3, 1)
    assert resolved["bucket"] == "month"
    assert shift_years(date(2028, 2, 29), -1) == date(2027, 2, 28)


def test_all_range_starts_at_the_first_month_and_has_no_previous():
    resolved = resolve_range("all", TODAY, date(2019, 5, 17))
    assert resolved["start"] == date(2019, 5, 1)
    assert resolved["end"] == TODAY
    assert resolved["bucket"] == "month"
    assert resolved["previous"] is None


def test_all_range_without_sessions_has_no_start():
    resolved = resolve_range("all", TODAY, None)
    assert resolved["start"] is None
    assert resolved["label"] == "All time"


def test_period_label_names_both_years_when_the_range_crosses_one():
    resolved = resolve_range("1y", date(2026, 1, 5), None)
    assert resolved["label"] == "6 Jan 2025 – 5 Jan 2026"


def test_partial_buckets_mark_the_leading_and_trailing_edges():
    start = date(2026, 1, 7)
    end = date(2026, 2, 3)
    info = partial_buckets(start, end, "week")
    first = info[date(2026, 1, 5)]
    assert first["partial"] is True
    assert first["note"] == "partial week, 5 of 7 days"
    last = info[date(2026, 2, 2)]
    assert last["partial"] is True
    assert last["in_progress"] is True
    assert last["note"] == "in progress"
    assert info[date(2026, 1, 12)]["partial"] is False


def test_partial_buckets_mark_month_ends():
    info = partial_buckets(date(2026, 1, 15), date(2026, 3, 10), "month")
    assert info[date(2026, 1, 1)]["note"] == "partial month, 17 of 31 days"
    assert info[date(2026, 2, 1)]["partial"] is False
    assert info[date(2026, 3, 1)]["in_progress"] is True


def test_delta_handles_missing_zero_percentage_and_absolute_values():
    assert delta(10, None) is None
    zero = delta(10, 0)
    assert zero["text"] == "—"
    assert "no value" in zero["aria"]

    up = delta(117, 100, comparison="the previous 12 weeks")
    assert up == {
        "text": "↑ 17%",
        "class": "up",
        "aria": "up 17 percent versus the previous 12 weeks",
    }
    down = delta(96, 100)
    assert down["text"] == "↓ 4%"
    assert down["class"] == "down"
    flat = delta(100, 100)
    assert flat["text"] == "—"

    absolute = delta(3.5, 3.1, absolute=True, suffix="/wk", comparison="the previous 4 weeks")
    assert absolute["text"] == "+0.4/wk"
    assert absolute["class"] == "up"
    negative = delta(2.9, 3.1, absolute=True, suffix="/wk", comparison="the previous 4 weeks")
    assert negative["text"] == "−0.2/wk"


def test_nice_max_uses_the_documented_steps():
    assert nice_max(0) == 1.0
    assert nice_max(-5) == 1.0
    assert nice_max(1) == 1.0
    assert nice_max(0.5) == 0.5
    assert nice_max(18) == 20.0
    assert nice_max(92.4) == 100.0
    assert nice_max(745) == 1000.0


def test_axis_ticks_are_zero_half_and_max():
    ticks = axis_ticks(20, "t")
    assert [tick["label"] for tick in ticks] == ["0t", "10t", "20t"]


def test_bar_chart_marks_partial_bars_and_stays_finite():
    points = [
        {"date": date(2026, 1, 5), "value": 10, "partial": True, "note": "in progress"},
        {"date": date(2026, 1, 12), "value": 0},
        {"date": date(2026, 1, 19), "value": 30},
    ]
    chart = bar_chart(points, unit="t", bucket="week", aria_label="Volume")
    assert chart["kind"] == "bars"
    assert len(chart["bars"]) == 3
    assert chart["bars"][0]["partial"] is True
    assert "in progress" in chart["bars"][0]["title"]
    assert chart["bars"][2]["height"] > 0
    assert chart["aria_label"] == "Volume"
    assert chart["empty"] is False
    for bar in chart["bars"]:
        assert all(isinstance(bar[key], float) for key in ("x", "y", "width", "height"))


def test_bar_chart_zero_series_collapses_to_a_one_unit_axis():
    points = [{"date": date(2026, 1, 5), "value": 0}]
    chart = bar_chart(points, unit="t", bucket="week", aria_label="Volume")
    assert chart["empty"] is True
    assert chart["ticks"][-1]["label"] == "1t"
    assert chart["bars"][0]["height"] == 0


def test_line_chart_projects_finite_points_and_labels():
    lines = [
        {"label": "2026", "points": [(1, 1.5), (32, 4.0)]},
        {"label": "2025", "points": [(1, 0.5), (32, 2.0)]},
    ]
    chart = line_chart(lines, x_max=366, x_ticks=[(1, "Jan"), (60, "Mar")], y_unit=" t")
    assert chart["kind"] == "lines"
    assert len(chart["lines"]) == 2
    for line in chart["lines"]:
        for pair in line["points"].split():
            x, y = pair.split(",")
            assert float(x) == float(x)
            assert float(y) == float(y)


def test_training_streaks_count_consecutive_days_and_hide_stale_current_runs():
    today = date(2026, 3, 10)
    dates = [
        date(2026, 3, 1),
        date(2026, 3, 2),
        date(2026, 3, 3),
        date(2026, 3, 8),
        date(2026, 3, 9),
    ]
    streaks = training_streaks(dates, today)
    assert streaks["longest"] == 3
    assert streaks["current"] == 2
    assert streaks["days"] == 5

    stale = training_streaks([date(2026, 1, 1), date(2026, 1, 2)], today)
    assert stale["longest"] == 2
    assert stale["current"] is None

    assert training_streaks([], today) == {
        "longest": 0,
        "current": None,
        "last": None,
        "days": 0,
    }


def test_metric_mapping_is_one_dictionary():
    assert METRIC_SERIES == {
        "volume": "volume",
        "sessions": "sessions",
        "time": "training-time",
    }


def make_user(username="report-user"):
    return get_user_model().objects.create_user(username=username, password="x")


def make_session(user, day, name="Session", program="Test", volume="0", sets=1):
    return WorkoutSession.objects.create(
        owner=user,
        session_date=day,
        program=program,
        workout_name=name,
        start_time=timezone.make_aware(datetime.combine(day, time(9, 0))),
        duration_min=60,
        set_count=sets,
        total_volume_kg=Decimal(volume),
    )


def make_set(session, exercise, *, order=1, weight="10", reps=5, volume=None):
    return WorkoutSet.objects.create(
        owner=session.owner,
        session=session,
        exercise=exercise,
        set_order=order,
        weight_kg=Decimal(weight) if weight is not None else None,
        reps=reps,
        set_time=timezone.make_aware(datetime.combine(session.session_date, time(9, order))),
        volume_kg=Decimal(volume if volume is not None else "0"),
    )


@pytest.mark.django_db
def test_session_span_and_dates_are_owner_and_program_scoped():
    user = make_user()
    other = make_user("other")
    make_session(user, date(2026, 1, 5), program="Push")
    make_session(user, date(2026, 2, 5), program="Pull")
    make_session(other, date(2025, 1, 1), program="Push")

    assert session_span(user) == {"first": date(2026, 1, 5), "last": date(2026, 2, 5)}
    assert session_span(user, "Push") == {"first": date(2026, 1, 5), "last": date(2026, 1, 5)}
    assert session_span(user, "Missing") == {"first": None, "last": None}
    assert session_dates(user, date(2026, 1, 1), date(2026, 3, 1)) == [
        date(2026, 1, 5),
        date(2026, 2, 5),
    ]
    assert session_dates(user, None, None, "Pull") == [date(2026, 2, 5)]


@pytest.mark.django_db
def test_series_for_range_chunks_a_long_history_by_calendar_year():
    user = make_user()
    rows = []
    current = date(2016, 1, 5)
    while current <= date(2026, 11, 5):
        rows.append(
            WorkoutSession(
                owner=user,
                session_date=current,
                program="Test",
                workout_name=f"Session {current.isoformat()}",
                start_time=timezone.make_aware(datetime.combine(current, time(9, 0))),
                duration_min=60,
                set_count=1,
                total_volume_kg=Decimal("100"),
            )
        )
        current = shift_months(current, 1)
    WorkoutSession.objects.bulk_create(rows)
    exercise = Exercise.objects.create(owner=user, name="Bench")
    WorkoutSet.objects.bulk_create(
        [
            WorkoutSet(
                owner=user,
                session=session,
                exercise=exercise,
                set_order=1,
                weight_kg=Decimal("10"),
                reps=10,
                set_time=session.start_time,
                volume_kg=Decimal("100"),
            )
            for session in WorkoutSession.objects.filter(owner=user)
        ]
    )

    start = date(2016, 1, 1)
    end = date(2026, 11, 5)
    assert (end - start).days > MAX_RANGE_DAYS
    merged = series_for_range(user, "volume", "month", start, end, False, None)
    buckets = [item["bucket_start"] for item in merged["items"]]
    assert len(buckets) == len(set(buckets))
    assert buckets[0] == "2016-01-01"
    assert buckets[-1] == "2026-11-01"
    assert (
        sum(item["value"] for item in merged["items"])
        == summary_data(user, start, end, None)["volume_kg"]
    )


def make_large_muscle_fixture(user):
    session = make_session(user, date(2026, 3, 1), sets=1100)
    exercises = [Exercise(owner=user, name=f"Exercise {index:04d}") for index in range(1000)]
    Exercise.objects.bulk_create(exercises)
    ExerciseMeta.objects.bulk_create(
        [
            ExerciseMeta(
                owner=user,
                exercise_name=f"Exercise {index:04d}",
                muscle_group=f"Group {index:04d}",
            )
            for index in range(1000)
        ]
    )
    bodyweight = Exercise.objects.create(owner=user, name="Push Up")
    ExerciseMeta.objects.create(owner=user, exercise_name="Push Up", muscle_group="Bodyweight")
    stored = {item.name: item for item in Exercise.objects.filter(owner=user)}
    sets = []
    for index in range(1000):
        sets.append(
            WorkoutSet(
                owner=user,
                session=session,
                exercise=stored[f"Exercise {index:04d}"],
                set_order=index + 1,
                weight_kg=Decimal("10"),
                reps=5,
                set_time=session.start_time,
                volume_kg=Decimal("50"),
                est_1rm_kg=Decimal("11.67"),
            )
        )
    for index in range(100):
        sets.append(
            WorkoutSet(
                owner=user,
                session=session,
                exercise=bodyweight,
                set_order=1001 + index,
                weight_kg=None,
                reps=10,
                set_time=session.start_time,
                volume_kg=Decimal("0"),
            )
        )
    WorkoutSet.objects.bulk_create(sets)


@pytest.mark.django_db
def test_muscle_card_keeps_a_high_set_bodyweight_group_and_folds_the_tail():
    from workouts.reports import muscle_totals

    user = make_user()
    make_large_muscle_fixture(user)
    rows = muscle_totals(user, None, None, None)
    assert len(rows) == 1001
    assert rows[-1]["key"] == "Bodyweight"
    assert rows[-1]["sets"] == 100

    card = muscle_totals_card(user, None, None, None)
    assert card["items"][0]["key"] == "Bodyweight"
    assert card["items"][0]["sets"] == 100
    assert len(card["items"]) == 9
    assert card["items"][-1]["key"] == "Other"
    assert card["items"][-1]["folded"] == 993
    assert card["total_sets"] == 1100


@pytest.mark.django_db
def test_muscle_totals_count_a_session_once_per_group():
    from workouts.reports import muscle_totals

    user = make_user()
    session = make_session(user, date(2026, 3, 1), sets=2)
    bench = Exercise.objects.create(owner=user, name="Bench")
    fly = Exercise.objects.create(owner=user, name="Fly")
    ExerciseMeta.objects.create(owner=user, exercise_name="Bench", muscle_group="Chest")
    ExerciseMeta.objects.create(owner=user, exercise_name="Fly", muscle_group="Chest")
    make_set(session, bench, order=1, volume="100")
    make_set(session, fly, order=2, volume="50")

    rows = muscle_totals(user, None, None, None)
    assert rows == [{"key": "Chest", "sessions": 1, "sets": 2, "volume_kg": 150.0}]
