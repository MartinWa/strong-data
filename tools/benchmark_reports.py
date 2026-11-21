import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from datetime import time as clock_time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SESSIONS = 2000
DEFAULT_SETS_PER_SESSION = 30
YEARS = 10
MUSCLES = (
    "Chest",
    "Back",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Quads",
    "Hamstrings",
    "Glutes",
    "Calves",
    "Core",
)
PAGE_BUDGET_SECONDS = 2.5
BLOCK_BUDGET_SECONDS = 1.0


def configure_django(database):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "strong_data.settings")
    os.environ.setdefault("STRONG_DEBUG", "true")
    os.environ["STRONG_DB_PATH"] = database
    import django

    django.setup()


def build_dataset(sessions, sets_per_session):
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone

    from workouts.models import Exercise, ExerciseMeta, WorkoutSession, WorkoutSet

    user, created = get_user_model().objects.get_or_create(username="benchmark")
    if not created:
        return user

    exercise_count = 40
    exercises = []
    for index in range(exercise_count):
        exercise = Exercise.objects.create(owner=user, name=f"Exercise {index:02d}")
        ExerciseMeta.objects.create(
            owner=user,
            exercise_name=exercise.name,
            muscle_group=MUSCLES[index % len(MUSCLES)],
        )
        exercises.append(exercise)

    today = timezone.localdate()
    start = today - timedelta(days=YEARS * 365)
    span_days = (today - start).days
    session_rows = []
    set_plans = []
    for index in range(sessions):
        day_offset = span_days if sessions == 1 else index * span_days // (sessions - 1)
        session_date = start + timedelta(days=day_offset)
        session_volume = Decimal(0)
        session_sets = []
        for order in range(1, sets_per_session + 1):
            exercise = exercises[(index + order) % exercise_count]
            weight = Decimal(20 + (index * 7 + order * 3) % 180)
            reps = 3 + (index + order) % 10
            volume = weight * reps
            session_volume += volume
            session_sets.append(
                {
                    "exercise": exercise,
                    "order": order,
                    "weight": weight,
                    "reps": reps,
                    "volume": volume,
                }
            )
        start_time = timezone.make_aware(datetime.combine(session_date, clock_time(9, index % 60)))
        session_rows.append(
            WorkoutSession(
                owner=user,
                session_date=session_date,
                program=f"Program {index % 8}",
                workout_name=f"Workout {index:04d}",
                start_time=start_time,
                duration_min=40 + index % 50,
                set_count=sets_per_session,
                total_volume_kg=session_volume,
            )
        )
        set_plans.append((start_time, session_sets))

    with transaction.atomic():
        created_sessions = WorkoutSession.objects.bulk_create(session_rows, batch_size=500)
        set_rows = []
        for session, (start_time, session_sets) in zip(created_sessions, set_plans, strict=True):
            for plan in session_sets:
                weight = plan["weight"]
                set_rows.append(
                    WorkoutSet(
                        owner=user,
                        session=session,
                        exercise=plan["exercise"],
                        set_order=plan["order"],
                        weight_kg=weight,
                        reps=plan["reps"],
                        set_time=start_time + timedelta(seconds=plan["order"] * 60),
                        volume_kg=plan["volume"],
                        est_1rm_kg=weight * (Decimal(1) + Decimal(plan["reps"]) / Decimal(30)),
                    )
                )
        WorkoutSet.objects.bulk_create(set_rows, batch_size=1000)
    return user


def measure(label, callable_, results):
    started = time.perf_counter()
    callable_()
    elapsed = time.perf_counter() - started
    results.append({"label": label, "seconds": round(elapsed, 3)})
    return elapsed


def run_benchmark(sessions, sets_per_session):
    from django.utils import timezone

    from api.queries import (
        curve_data,
        muscle_totals,
        pace_data,
        personal_best_data,
        summary_data,
        yearly_data,
    )
    from workouts.reports import (
        _consistency_card,
        build_report,
        muscle_totals_card,
        resolve_range,
        series_for_range,
        session_span,
    )

    user = build_dataset(sessions, sets_per_session)
    today = timezone.localdate()
    span = session_span(user)
    results = []

    measure("session span", lambda: session_span(user), results)
    measure(
        "summary (all)",
        lambda: summary_data(user, span["first"], today, None),
        results,
    )

    ranges = {
        "12w": resolve_range("12w", today, span["first"]),
        "1y": resolve_range("1y", today, span["first"]),
        "all": resolve_range("all", today, span["first"]),
    }
    for key, resolved in ranges.items():
        measure(
            f"series volume ({key})",
            lambda r=resolved: series_for_range(
                user, "volume", r["bucket"], r["start"], r["end"], False, None
            ),
            results,
        )
    measure(
        "muscle totals (all)",
        lambda: muscle_totals(user, ranges["all"]["start"], today, None),
        results,
    )
    measure(
        "muscle card (all)",
        lambda: muscle_totals_card(user, ranges["all"]["start"], today, None),
        results,
    )
    measure(
        "consistency card (all)",
        lambda: _consistency_card(user, ranges["all"]["start"], today, today, None),
        results,
    )
    measure(
        "personal bests (all)",
        lambda: personal_best_data(user, ranges["all"]["start"], today, None),
        results,
    )
    measure("yearly totals", lambda: yearly_data(user, None), results)
    measure(
        "yearly curve (current)",
        lambda: curve_data(user, today.year, [today.year, today.year - 1], today, None),
        results,
    )
    measure(
        "pace (current)",
        lambda: pace_data(user, today.year, today, None),
        results,
    )

    def recent_page():
        context = build_report(user, {"range": "12w"}, today)
        if context.get("range_empty"):
            raise RuntimeError("benchmark dataset has no sessions in the recent range")
        return context

    measure("build_report (12w)", recent_page, results)
    measure("build_report (all)", lambda: build_report(user, {"range": "all"}, today), results)
    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark the report query layer.")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--sets-per-session", type=int, default=DEFAULT_SETS_PER_SESSION)
    parser.add_argument("--database", default=None, help="SQLite path; defaults to a temp file.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--budget",
        type=float,
        default=PAGE_BUDGET_SECONDS,
        help="Full-page budget in seconds; 0 disables the check.",
    )
    parser.add_argument(
        "--block-budget",
        type=float,
        default=BLOCK_BUDGET_SECONDS,
        help="Per-block budget in seconds; 0 disables the check.",
    )
    args = parser.parse_args()

    database = args.database
    if database is None:
        database = str(Path(tempfile.mkdtemp()) / "benchmark.sqlite3")
    configure_django(database)
    from django.core.management import call_command

    call_command("migrate", verbosity=0, interactive=False)
    results = run_benchmark(args.sessions, args.sets_per_session)

    payload = {
        "dataset": {
            "sessions": args.sessions,
            "sets_per_session": args.sets_per_session,
            "sets": args.sessions * args.sets_per_session,
            "years": YEARS,
        },
        "timings": results,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Dataset: {args.sessions} sessions, "
            f"{args.sessions * args.sets_per_session} sets over {YEARS} years"
        )
        for item in results:
            print(f"{item['label']:<28} {item['seconds']:>8.3f} s")

    failures = []
    page = next(item for item in results if item["label"] == "build_report (all)")
    if args.budget and page["seconds"] > args.budget:
        failures.append(f"full page {page['seconds']:.3f}s exceeds {args.budget:.3f}s")
    if args.block_budget:
        for item in results:
            if item["label"].startswith("build_report"):
                continue
            if item["seconds"] > args.block_budget:
                failures.append(
                    f"{item['label']} {item['seconds']:.3f}s exceeds {args.block_budget:.3f}s"
                )
    if failures:
        for failure in failures:
            print(f"BUDGET FAILURE: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
