from dataclasses import dataclass
from datetime import UTC

from django.db import transaction
from django.utils import timezone

from parsing import ParsedWorkouts, classify_muscle, parse_workouts

from .models import Exercise, ExerciseMeta, WorkoutSession, WorkoutSet


@dataclass(frozen=True)
class ImportResult:
    sessions: int
    sets: int
    exercises: int


def import_workouts(user, parsed: ParsedWorkouts) -> ImportResult:
    with transaction.atomic():
        WorkoutSet.objects.filter(owner=user).delete()
        WorkoutSession.objects.filter(owner=user).delete()
        Exercise.objects.filter(owner=user).delete()

        exercises = {}
        for name in parsed.exercises:
            exercise, _ = Exercise.objects.get_or_create(owner=user, name=name)
            exercises[name] = exercise
            ExerciseMeta.objects.get_or_create(
                owner=user,
                exercise_name=name,
                defaults={"muscle_group": classify_muscle(name)},
            )

        session_rows = [
            WorkoutSession(
                owner=user,
                session_date=item.session_date,
                program=item.program,
                workout_name=item.workout_name,
                start_time=timezone.make_aware(item.start_time, UTC),
                duration_min=item.duration_min,
                set_count=item.set_count,
                total_volume_kg=item.total_volume_kg,
            )
            for item in parsed.sessions
        ]
        created_sessions = WorkoutSession.objects.bulk_create(session_rows)

        set_rows = []
        for parsed_session, session in zip(parsed.sessions, created_sessions, strict=True):
            for item in parsed_session.sets:
                set_rows.append(
                    WorkoutSet(
                        owner=user,
                        session=session,
                        exercise=exercises[item.exercise_name],
                        set_order=item.set_order,
                        weight_kg=item.weight_kg,
                        reps=item.reps,
                        rpe=item.rpe,
                        distance=item.distance,
                        seconds=item.seconds,
                        set_time=timezone.make_aware(item.set_time, UTC),
                        volume_kg=item.volume_kg,
                        est_1rm_kg=item.est_1rm_kg,
                    )
                )
        WorkoutSet.objects.bulk_create(set_rows)

    return ImportResult(
        sessions=len(created_sessions),
        sets=len(set_rows),
        exercises=len(exercises),
    )


def import_workouts_csv(user, text: str) -> ImportResult:
    return import_workouts(user, parse_workouts(text))
