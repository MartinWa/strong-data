from decimal import Decimal
from itertools import batched

from django.db import migrations, models
from django.db.models import Count, Max, Sum

BATCH_SIZE = 500
VALUE_FIELDS = ("weight_kg", "reps", "rpe", "distance", "seconds", "volume_kg", "est_1rm_kg")


def dedup_set_keys(apps, schema_editor):
    WorkoutSet = apps.get_model("workouts", "WorkoutSet")
    WorkoutSession = apps.get_model("workouts", "WorkoutSession")
    sets = WorkoutSet.objects.using(schema_editor.connection.alias)
    sessions = WorkoutSession.objects.using(schema_editor.connection.alias)
    session_max = {
        row["session_id"]: row["max_order"]
        for row in sets.values("session_id").annotate(max_order=Max("set_order"))
    }
    kept = {}
    stale = []
    renumber = []
    affected = set()
    rows = sets.order_by("id").values_list(
        "id", "session_id", "exercise_id", "set_order", "set_time", *VALUE_FIELDS
    )
    for row in rows.iterator(chunk_size=BATCH_SIZE):
        pk, session_id, exercise_id, set_order, set_time = row[:5]
        values = row[5:]
        key = (session_id, exercise_id, set_order, set_time)
        if key in kept:
            affected.add(session_id)
            if values in kept[key]:
                stale.append(pk)
            else:
                kept[key].add(values)
                session_max[session_id] += 1
                renumber.append((pk, session_max[session_id], set_order))
        else:
            kept[key] = {values}
    for batch in batched(stale, BATCH_SIZE, strict=False):
        sets.filter(pk__in=batch).delete()
    for pk, order, source_order in renumber:
        sets.filter(pk=pk).update(set_order=order, source_set_order=source_order)
    for batch in batched(affected, BATCH_SIZE, strict=False):
        rows = (
            sets.filter(session_id__in=batch)
            .values("session_id")
            .annotate(count=Count("id"), volume=Sum("volume_kg"))
        )
        for row in rows:
            sessions.filter(id=row["session_id"]).update(
                set_count=row["count"],
                total_volume_kg=row["volume"] or Decimal(0),
            )


class Migration(migrations.Migration):
    dependencies = [("workouts", "0004_split_core_into_abs")]

    operations = [
        migrations.AddField(
            model_name="workoutset",
            name="source_set_order",
            field=models.IntegerField(null=True, editable=False),
        ),
        migrations.RunPython(dedup_set_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="workoutset",
            constraint=models.UniqueConstraint(
                fields=["session", "exercise", "set_order", "set_time"],
                name="uniq_set_session_exercise_order_time",
            ),
        ),
    ]
