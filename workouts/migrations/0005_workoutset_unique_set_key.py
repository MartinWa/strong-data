from django.db import migrations, models


def dedup_set_keys(apps, schema_editor):
    WorkoutSet = apps.get_model("workouts", "WorkoutSet")
    seen = set()
    stale = []
    rows = WorkoutSet.objects.order_by("id").values_list(
        "id", "session_id", "exercise_id", "set_order", "set_time"
    )
    for pk, session_id, exercise_id, set_order, set_time in rows:
        key = (session_id, exercise_id, set_order, set_time)
        if key in seen:
            stale.append(pk)
        else:
            seen.add(key)
    if stale:
        WorkoutSet.objects.filter(pk__in=stale).delete()


class Migration(migrations.Migration):
    dependencies = [("workouts", "0004_split_core_into_abs")]

    operations = [
        migrations.RunPython(dedup_set_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="workoutset",
            constraint=models.UniqueConstraint(
                fields=["session", "exercise", "set_order", "set_time"],
                name="uniq_set_session_exercise_order_time",
            ),
        ),
    ]
