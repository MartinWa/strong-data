from django.db import migrations

HEURISTIC_GROUPS = (
    "Biceps",
    "Calves",
    "Chest",
    "Core",
    "Glutes",
    "Hamstrings",
    "Lats",
    "Lower Back",
    "Other",
    "Quads",
    "Shoulders",
    "Triceps",
    "Upper Back",
)


def merge_duplicate_groups(apps, schema_editor):
    ExerciseMeta = apps.get_model("workouts", "ExerciseMeta")
    heuristic = {name.casefold(): name for name in HEURISTIC_GROUPS}
    owner_ids = ExerciseMeta.objects.values_list("owner_id", flat=True).distinct()
    for owner_id in owner_ids:
        rows = ExerciseMeta.objects.filter(owner_id=owner_id).values_list("id", "muscle_group")
        variants = {}
        for pk, value in rows:
            name = " ".join((value or "").split())
            variants.setdefault(name.casefold(), []).append((pk, value, name))
        for key, entries in variants.items():
            representative = heuristic.get(key) or min(name for _, _, name in entries)
            stale = [pk for pk, value, _ in entries if value != representative]
            if stale:
                ExerciseMeta.objects.filter(pk__in=stale).update(muscle_group=representative)


class Migration(migrations.Migration):
    dependencies = [("workouts", "0002_alter_apitoken_prefix")]

    operations = [migrations.RunPython(merge_duplicate_groups, migrations.RunPython.noop)]
