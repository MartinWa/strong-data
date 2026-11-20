from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from workouts.models import ExerciseMeta, WorkoutSession, WorkoutSet
from workouts.services import EmptyImportError, import_workouts_csv

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE"


def csv_text(*rows: str) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"


FIRST_EXPORT = csv_text(
    "2026-01-05 09:00:00,Push Day #1,54m,Bench Press (Barbell),2,80,5,0,0,8.0",
    "2026-01-05 08:30:00,Push Day #1,54m,Bench Press (Barbell),1,80,5,0,0,7.5",
    "2026-01-05 08:35:00,Push Day #1,54m,Chest Fly,1,,,0,0,",
)

SECOND_EXPORT = csv_text(
    "2026-02-01 07:00:00,Pull Day,1h,Seated Row (Cable),1,60,10,0,0,9.0",
)


@pytest.mark.django_db
def test_import_stores_owner_scoped_rows_and_derived_fields():
    user = get_user_model().objects.create_user(username="alice", password="x")

    result = import_workouts_csv(user, FIRST_EXPORT)

    assert (result.sessions, result.sets, result.exercises) == (1, 3, 2)
    session = WorkoutSession.objects.get(owner=user)
    assert session.program == "Push Day"
    assert session.workout_name == "Push Day #1"
    assert session.set_count == 3
    assert session.total_volume_kg == Decimal("800.00")

    sets = list(WorkoutSet.objects.filter(owner=user).order_by("set_time"))
    assert len(sets) == 3

    weighted = sets[0]
    assert weighted.exercise.name == "Bench Press (Barbell)"
    assert weighted.weight_kg == Decimal("80.00")
    assert weighted.volume_kg == Decimal("400.00")
    assert weighted.rpe == Decimal("7.5")

    bodyweight = sets[1]
    assert bodyweight.exercise.name == "Chest Fly"
    assert bodyweight.weight_kg is None
    assert bodyweight.volume_kg == Decimal("0.00")
    assert bodyweight.est_1rm_kg is None


@pytest.mark.django_db
def test_wall_clock_times_are_read_in_the_configured_zone():
    user = get_user_model().objects.create_user(username="tz", password="x")

    with override_settings(TIME_ZONE="Europe/Stockholm"):
        import_workouts_csv(user, FIRST_EXPORT)

    session = WorkoutSession.objects.get(owner=user)
    assert session.start_time == datetime(2026, 1, 5, 7, 30, tzinfo=UTC)
    assert list(WorkoutSet.objects.filter(owner=user).order_by("set_time"))[0].set_time == datetime(
        2026, 1, 5, 7, 30, tzinfo=UTC
    )


@pytest.mark.django_db
def test_utc_remains_the_default_for_imports():
    user = get_user_model().objects.create_user(username="utc", password="x")

    import_workouts_csv(user, FIRST_EXPORT)

    session = WorkoutSession.objects.get(owner=user)
    assert session.start_time == datetime(2026, 1, 5, 8, 30, tzinfo=UTC)


@pytest.mark.django_db
def test_reimport_is_idempotent_and_preserves_meta_corrections():
    user = get_user_model().objects.create_user(username="bob", password="x")

    import_workouts_csv(user, FIRST_EXPORT)
    ExerciseMeta.objects.filter(owner=user, exercise_name="Chest Fly").update(
        muscle_group="Corrected"
    )
    first_ids = set(WorkoutSession.objects.filter(owner=user).values_list("id", flat=True))

    result = import_workouts_csv(user, FIRST_EXPORT)

    assert (result.sessions, result.sets, result.exercises) == (1, 3, 2)
    assert WorkoutSession.objects.filter(owner=user).count() == 1
    assert WorkoutSet.objects.filter(owner=user).count() == 3
    assert set(WorkoutSession.objects.filter(owner=user).values_list("id", flat=True)) != first_ids
    assert (
        ExerciseMeta.objects.get(owner=user, exercise_name="Chest Fly").muscle_group == "Corrected"
    )

    import_workouts_csv(user, SECOND_EXPORT)
    assert (
        ExerciseMeta.objects.get(owner=user, exercise_name="Chest Fly").muscle_group == "Corrected"
    )
    assert WorkoutSession.objects.filter(owner=user).count() == 1
    assert WorkoutSet.objects.filter(owner=user).count() == 1


@pytest.mark.django_db
def test_import_does_not_touch_other_owners():
    alice = get_user_model().objects.create_user(username="alice", password="x")
    bob = get_user_model().objects.create_user(username="bob", password="x")

    import_workouts_csv(alice, FIRST_EXPORT)
    import_workouts_csv(bob, SECOND_EXPORT)
    import_workouts_csv(alice, SECOND_EXPORT)

    assert WorkoutSession.objects.filter(owner=alice).count() == 1
    assert WorkoutSession.objects.filter(owner=bob).count() == 1
    assert WorkoutSet.objects.filter(owner=alice).count() == 1
    assert WorkoutSet.objects.filter(owner=bob).count() == 1
    assert WorkoutSession.objects.get(owner=alice).workout_name == "Pull Day"
    assert WorkoutSession.objects.get(owner=bob).workout_name == "Pull Day"


@pytest.mark.django_db
def test_empty_import_does_not_erase_existing_workouts():
    user = get_user_model().objects.create_user(username="alice", password="x")
    import_workouts_csv(user, FIRST_EXPORT)

    with pytest.raises(EmptyImportError):
        import_workouts_csv(user, HEADER + "\n")
    with pytest.raises(EmptyImportError):
        import_workouts_csv(user, csv_text("not-a-date,Push Day,54m,Bench,1,80,5,0,0,8"))

    assert WorkoutSession.objects.filter(owner=user).count() == 1
    assert WorkoutSet.objects.filter(owner=user).count() == 3


@pytest.mark.django_db
def test_out_of_range_weight_can_be_read_back():
    user = get_user_model().objects.create_user(username="alice", password="x")

    import_workouts_csv(
        user,
        csv_text("2026-01-05 08:00:00,Push,54m,Bench,1,1000000,5,0,0,8"),
    )

    workout_set = WorkoutSet.objects.get(owner=user)
    assert workout_set.weight_kg is None
    assert workout_set.volume_kg == Decimal("0.00")
    assert workout_set.est_1rm_kg is None
