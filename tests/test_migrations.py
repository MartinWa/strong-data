import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

MERGE_BEFORE = [("workouts", "0002_alter_apitoken_prefix")]
MERGE_AFTER = [("workouts", "0003_merge_duplicate_muscle_groups")]
SPLIT_AFTER = [("workouts", "0004_split_core_into_abs")]


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
