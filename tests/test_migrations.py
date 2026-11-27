from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

MERGE_BEFORE = [("workouts", "0002_alter_apitoken_prefix")]
MERGE_AFTER = [("workouts", "0003_merge_duplicate_muscle_groups")]
SPLIT_AFTER = [("workouts", "0004_split_core_into_abs")]
DEDUP_BEFORE = [("workouts", "0004_split_core_into_abs")]
DEDUP_AFTER = [("workouts", "0005_workoutset_unique_set_key")]


@pytest.mark.django_db(transaction=True)
def test_duplicate_muscle_groups_are_merged_per_owner():
    executor = MigrationExecutor(connection)
    executor.migrate(MERGE_BEFORE)
    apps = executor.loader.project_state(MERGE_BEFORE).apps
    User = apps.get_model("auth", "User")
    ExerciseMeta = apps.get_model("workouts", "ExerciseMeta")
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    ExerciseMeta.objects.create(owner_id=alice.pk, exercise_name="A", muscle_group="chest")
    ExerciseMeta.objects.create(owner_id=alice.pk, exercise_name="B", muscle_group=" Chest ")
    ExerciseMeta.objects.create(owner_id=alice.pk, exercise_name="C", muscle_group="my  group")
    ExerciseMeta.objects.create(owner_id=alice.pk, exercise_name="D", muscle_group="my group")
    ExerciseMeta.objects.create(owner_id=bob.pk, exercise_name="A", muscle_group="CHEST")

    executor = MigrationExecutor(connection)
    executor.migrate(SPLIT_AFTER)
    apps = executor.loader.project_state(SPLIT_AFTER).apps
    ExerciseMeta = apps.get_model("workouts", "ExerciseMeta")

    alice_groups = dict(
        ExerciseMeta.objects.filter(owner_id=alice.pk).values_list("exercise_name", "muscle_group")
    )
    bob_groups = dict(
        ExerciseMeta.objects.filter(owner_id=bob.pk).values_list("exercise_name", "muscle_group")
    )
    assert alice_groups == {
        "A": "Chest",
        "B": "Chest",
        "C": "my group",
        "D": "my group",
    }
    assert bob_groups == {"A": "Chest"}


@pytest.mark.django_db(transaction=True)
def test_core_splits_into_abs_for_flexion_exercises():
    executor = MigrationExecutor(connection)
    executor.migrate(MERGE_AFTER)
    apps = executor.loader.project_state(MERGE_AFTER).apps
    User = apps.get_model("auth", "User")
    ExerciseMeta = apps.get_model("workouts", "ExerciseMeta")
    alice = User.objects.create(username="alice")
    rows = [
        ("Crunch (Machine)", "Core"),
        ("Cable Crunch", "core"),
        ("Decline Sit-Up", "Core"),
        ("Plank", "Core"),
        ("Russian Twist", "Core"),
        ("Sled Push", "Core"),
        ("Leg Extension (Machine)", "abs"),
        ("Dead Bug", "ABs"),
        ("Side Bend (Dumbbell)", "CORE"),
        ("Chest Fly", "Chest"),
    ]
    for name, group in rows:
        ExerciseMeta.objects.create(owner_id=alice.pk, exercise_name=name, muscle_group=group)

    executor = MigrationExecutor(connection)
    executor.migrate(SPLIT_AFTER)
    apps = executor.loader.project_state(SPLIT_AFTER).apps
    ExerciseMeta = apps.get_model("workouts", "ExerciseMeta")

    groups = dict(
        ExerciseMeta.objects.filter(owner_id=alice.pk).values_list("exercise_name", "muscle_group")
    )
    assert groups == {
        "Crunch (Machine)": "Abs",
        "Cable Crunch": "Abs",
        "Decline Sit-Up": "Abs",
        "Plank": "Core",
        "Russian Twist": "Core",
        "Sled Push": "Core",
        "Leg Extension (Machine)": "Abs",
        "Dead Bug": "Abs",
        "Side Bend (Dumbbell)": "Core",
        "Chest Fly": "Chest",
    }


@pytest.mark.django_db(transaction=True)
def test_duplicate_set_keys_are_renumbered_or_dropped_and_totals_recomputed():
    executor = MigrationExecutor(connection)
    executor.migrate(DEDUP_BEFORE)
    apps = executor.loader.project_state(DEDUP_BEFORE).apps
    User = apps.get_model("auth", "User")
    WorkoutSession = apps.get_model("workouts", "WorkoutSession")
    Exercise = apps.get_model("workouts", "Exercise")
    WorkoutSet = apps.get_model("workouts", "WorkoutSet")
    user = User.objects.create(username="alice")
    session = WorkoutSession.objects.create(
        owner_id=user.pk,
        session_date=date(2026, 1, 5),
        program="Push Day",
        workout_name="Push Day #1",
        start_time=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        set_count=99,
        total_volume_kg=Decimal("12345.00"),
    )
    exercise = Exercise.objects.create(owner_id=user.pk, name="Bench Press (Barbell)")
    shared = {
        "owner_id": user.pk,
        "session_id": session.pk,
        "exercise_id": exercise.pk,
        "set_order": 1,
        "set_time": datetime(2026, 1, 5, 8, 30, tzinfo=UTC),
        "reps": 5,
    }
    first = WorkoutSet.objects.create(
        **shared, weight_kg=Decimal("80.00"), volume_kg=Decimal("400.00")
    )
    renumbered = WorkoutSet.objects.create(
        **shared, weight_kg=Decimal("82.00"), volume_kg=Decimal("410.00")
    )
    WorkoutSet.objects.create(**shared, weight_kg=Decimal("82.00"), volume_kg=Decimal("410.00"))
    other = WorkoutSet.objects.create(
        **{**shared, "set_order": 2, "set_time": datetime(2026, 1, 5, 8, 35, tzinfo=UTC)},
        weight_kg=Decimal("80.00"),
        volume_kg=Decimal("400.00"),
    )

    executor = MigrationExecutor(connection)
    executor.migrate(DEDUP_AFTER)
    apps = executor.loader.project_state(DEDUP_AFTER).apps
    WorkoutSet = apps.get_model("workouts", "WorkoutSet")
    WorkoutSession = apps.get_model("workouts", "WorkoutSession")

    rows = list(WorkoutSet.objects.filter(session_id=session.pk).order_by("id"))
    assert [row.pk for row in rows] == [first.pk, renumbered.pk, other.pk]
    assert len(rows) == 3
    assert rows[0].set_order == 1
    assert rows[0].source_set_order is None
    assert rows[0].weight_kg == Decimal("80.00")
    assert rows[1].weight_kg == Decimal("82.00")
    assert rows[1].set_order == 3
    assert rows[1].source_set_order == 1
    session = WorkoutSession.objects.get(pk=session.pk)
    assert session.set_count == 3
    assert session.total_volume_kg == Decimal("1210.00")
    assert any(
        constraint.name == "uniq_set_session_exercise_order_time"
        for constraint in WorkoutSet._meta.constraints
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkoutSet.objects.create(**shared, weight_kg=Decimal("90.00"), volume_kg=Decimal("450.00"))
