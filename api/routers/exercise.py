from typing import Literal

from ninja import Router

from ..contract import envelope
from ..params import OptDateParam, StrictQuery, validate_date_range
from ..queries import exercise_record_data, progress_data
from ..schemas import ExerciseRecordOut, ProgressOut

router = Router()


@router.get(
    "/exercises/{path:name}/progress",
    response=ProgressOut,
    tags=["exercise"],
    summary="Daily exercise progress",
)
def exercise_progress(
    request,
    name: str,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    group_by: Literal["day", "session"] = StrictQuery("day"),
):
    validate_date_range(start, end)
    return {**envelope(), **progress_data(request.auth, name, start, end, group_by)}


@router.get(
    "/exercises/{path:name}/records",
    response=ExerciseRecordOut,
    tags=["exercise"],
    summary="Exercise records by reps",
)
def exercise_records(
    request,
    name: str,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
):
    validate_date_range(start, end)
    return {**envelope(), **exercise_record_data(request.auth, name, start, end)}
