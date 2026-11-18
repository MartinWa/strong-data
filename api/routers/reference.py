from ninja import Router

from workouts.models import Exercise, ExerciseMeta, WorkoutSession

from ..contract import envelope
from ..params import NoQuery, StrictQuery
from ..schemas import ValuesOut

router = Router()


@router.get("/programs", response=ValuesOut, tags=["reference"], summary="Distinct programs")
def programs(request, query: NoQuery = StrictQuery(None)):
    values = sorted(
        {
            value
            for value in WorkoutSession.objects.filter(owner=request.auth).values_list(
                "program", flat=True
            )
        }
    )
    return {**envelope(), "items": values, "count": len(values)}


@router.get("/exercises", response=ValuesOut, tags=["reference"], summary="Distinct exercises")
def exercises(request, query: NoQuery = StrictQuery(None)):
    values = list(
        Exercise.objects.filter(owner=request.auth).values_list("name", flat=True).order_by("name")
    )
    return {**envelope(), "items": values, "count": len(values)}


@router.get(
    "/muscle-groups", response=ValuesOut, tags=["reference"], summary="Distinct muscle groups"
)
def muscle_groups(request, query: NoQuery = StrictQuery(None)):
    values = sorted(
        {
            value
            for value in ExerciseMeta.objects.filter(owner=request.auth).values_list(
                "muscle_group", flat=True
            )
        }
    )
    return {**envelope(), "items": values, "count": len(values)}
