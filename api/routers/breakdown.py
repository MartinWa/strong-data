from ninja import Router

from ..contract import envelope
from ..params import IntParam, OptDateParam, StrictQuery, validate_date_range, validate_pagination
from ..queries import breakdown_data
from ..schemas import BreakdownOut

router = Router()


def _build(request, dimension, start, end, limit):
    validate_date_range(start, end)
    validate_pagination(limit, 0)
    return {**envelope(), **breakdown_data(request.auth, dimension, start, end, limit)}


@router.get(
    "/breakdown/weekday", response=BreakdownOut, tags=["breakdown"], summary="Weekday breakdown"
)
def breakdown_weekday(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
):
    return _build(request, "weekday", start, end, limit)


@router.get(
    "/breakdown/program", response=BreakdownOut, tags=["breakdown"], summary="Program breakdown"
)
def breakdown_program(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
):
    return _build(request, "program", start, end, limit)


@router.get(
    "/breakdown/muscle", response=BreakdownOut, tags=["breakdown"], summary="Muscle breakdown"
)
def breakdown_muscle(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
):
    return _build(request, "muscle", start, end, limit)


@router.get(
    "/breakdown/exercises",
    response=BreakdownOut,
    tags=["breakdown"],
    summary="Exercise breakdown",
)
def breakdown_exercises(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
):
    return _build(request, "exercises", start, end, limit)
