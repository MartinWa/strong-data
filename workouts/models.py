import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class Exercise(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="exercises",
    )
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_exercise_owner_name")
        ]

    def __str__(self):
        return self.name


class ExerciseMeta(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="exercise_meta",
    )
    exercise_name = models.CharField(max_length=255)
    muscle_group = models.CharField(max_length=64)

    class Meta:
        ordering = ["exercise_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "exercise_name"], name="uniq_exercise_meta_owner_name"
            )
        ]

    def __str__(self):
        return self.exercise_name


class WorkoutSession(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    session_date = models.DateField()
    program = models.CharField(max_length=255)
    workout_name = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    duration_min = models.IntegerField(null=True, blank=True)
    set_count = models.IntegerField(default=0)
    total_volume_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["session_date", "workout_name"]
        indexes = [models.Index(fields=["session_date"], name="ix_session_date")]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "session_date", "workout_name"],
                name="uniq_session_owner_date_name",
            ),
            models.CheckConstraint(
                condition=models.Q(set_count__gte=0), name="check_session_count_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(total_volume_kg__gte=0),
                name="check_session_volume_positive",
            ),
        ]

    def __str__(self):
        return f"{self.session_date} {self.workout_name}"

    def sets_by_exercise(self):
        groups = []
        positions = {}
        for item in self.sets.all():
            position = positions.setdefault(item.exercise_id, len(groups))
            if position == len(groups):
                groups.append({"exercise": item.exercise, "sets": []})
            groups[position]["sets"].append(item)
        return groups


class WorkoutSet(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sets",
    )
    session = models.ForeignKey(
        WorkoutSession,
        on_delete=models.CASCADE,
        related_name="sets",
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
        related_name="sets",
    )
    set_order = models.IntegerField()
    weight_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    reps = models.IntegerField(default=0)
    rpe = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    distance = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    seconds = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    set_time = models.DateTimeField()
    volume_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    est_1rm_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["set_time", "set_order"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(set_order__gte=1), name="check_set_order_positive"
            ),
            models.CheckConstraint(condition=models.Q(reps__gte=0), name="check_set_reps_positive"),
            models.CheckConstraint(
                condition=models.Q(volume_kg__gte=0), name="check_set_volume_positive"
            ),
            models.UniqueConstraint(
                fields=["session", "exercise", "set_order", "set_time"],
                name="uniq_set_session_exercise_order_time",
            ),
        ]

    def __str__(self):
        return f"{self.exercise.name} {self.set_order}"


class ApiToken(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=255)
    key_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=16, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_token_owner_name")
        ]

    @classmethod
    def generate(cls, owner, name, expires_at=None):
        secret = secrets.token_urlsafe(32)
        assert len(secret) >= 32, "token secret is too short"  # noqa: S101
        instance = cls(
            owner=owner,
            name=name,
            key_hash=hashlib.sha256(secret.encode()).hexdigest(),
            prefix=secret[:8],
            expires_at=expires_at,
        )
        instance.save()
        return instance, secret

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_active(self):
        return self.revoked_at is None and not self.is_expired

    def __str__(self):
        return self.name
