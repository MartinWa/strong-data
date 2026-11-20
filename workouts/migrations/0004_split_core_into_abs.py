from django.db import migrations

FLEXION_KEYWORDS = ("crunch", "sit up", "sit-up", "leg raise")
CANONICAL = {"abs": "Abs", "core": "Core"}


def split_core_into_abs(apps, schema_editor):
    ExerciseMeta = apps.get_model("workouts", "ExerciseMeta")
    rows = ExerciseMeta.objects.filter(muscle_group__iexact="Core").values_list(
        "id", "exercise_name"
    )
    flexion = [
        pk
        for pk, name in rows
        if any(keyword in (name or "").lower() for keyword in FLEXION_KEYWORDS)
    ]
    if flexion:
        ExerciseMeta.objects.filter(pk__in=flexion).update(muscle_group="Abs")
    for key, spelling in CANONICAL.items():
        ExerciseMeta.objects.filter(muscle_group__iexact=key).exclude(muscle_group=spelling).update(
            muscle_group=spelling
        )


class Migration(migrations.Migration):
    dependencies = [("workouts", "0003_merge_duplicate_muscle_groups")]

    operations = [migrations.RunPython(split_core_into_abs, migrations.RunPython.noop)]
