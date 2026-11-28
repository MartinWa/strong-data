import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workouts", "0005_workoutset_unique_set_key")]

    operations = [
        migrations.AddField(
            model_name="workoutsession",
            name="import_time_zone",
            field=models.CharField(
                default=django.utils.timezone.get_default_timezone_name,
                editable=False,
                max_length=64,
            ),
        ),
    ]
