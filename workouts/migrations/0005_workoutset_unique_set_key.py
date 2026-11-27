from decimal import Decimal

from django.db import migrations, models
from django.db.models import Count, Max, Sum

VALUE_FIELDS = ("weight_kg", "reps", "rpe", "distance", "seconds")


def dedup_set_keys(apps, schema_editor):
    WorkoutSet = apps.get_model("workouts", "WorkoutSet")
    WorkoutSession = apps.get_model("workouts", "WorkoutSession")
    session_max = {
        row["session_id"]: row["max_order"]
        for row in WorkoutSet.objects.values("session_id").annotate(max_order=Max("set_order"))
    }
    kept = {}
    stale = []
    renumber = []
    for row in WorkoutSet.objects.order_by("id").values_list(
        "id", "session_id", "exercise_id", "set_order", "set_time", *VALUE_FIELDS
    ):
        pk, session_id, exercise_id, set_order, set_time = row[:5]
        values = row[5:]
        key = (session_id, exercise_id, set_order, set_time)
        if key in kept:
            if values in kept[key]:
                stale.append((pk, session_id))
            else:
                kept[key].add(values)
                session_max[session_id] += 1
                renumber.append((pk, session_id, session_max[session_id]))
        else:
            kept[key] = {values}
    if stale:
        WorkoutSet.objects.filter(pk__in=[pk for pk, _ in stale]).delete()
    for pk, _session_id, order in renumber:
        WorkoutSet.objects.filter(pk=pk).update(set_order=order)
    affected = {session_id for _pk, session_id in stale} | {
        session_id for _pk, session_id, _order in renumber
    }
    if affected:
        rows = (
            WorkoutSet.objects.filter(session_id__in=affected)
            .values("session_id")
            .annotate(count=Count("id"), volume=Sum("volume_kg"))
        )
        for row in rows:
            WorkoutSession.objects.filter(id=row["session_id"]).update(
                set_count=row["count"],
                total_volume_kg=row["volume"] or Decimal(0),
            )


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
