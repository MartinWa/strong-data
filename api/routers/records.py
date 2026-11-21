from typing import Literal

from ninja import Router

from ..contract import envelope
from ..params import OptDateParam, OptFilterParam, StrictQuery, validate_date_range
from ..queries import bodyweight_record_data, est_1rm_record_data, personal_best_data
from ..schemas import BodyweightRecordOut, Est1rmRecordOut, PersonalBestOut

router = Router()

PersonalBestKind = Literal["strength", "bodyweight"] | None


@router.get(
    "/records/est-1rm",
    response=Est1rmRecordOut,
    tags=["records"],
    summary="Best estimated 1RM per exercise",
)
def est_1rm_records(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: OptFilterParam = StrictQuery(None),
):
    validate_date_range(start, end)
    return {**envelope(), **est_1rm_record_data(request.auth, start, end, program)}


@router.get(
    "/records/bodyweight",
    response=BodyweightRecordOut,
    tags=["records"],
    summary="Best bodyweight set per exercise",
)
def bodyweight_records(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: OptFilterParam = StrictQuery(None),
):
    validate_date_range(start, end)
    return {**envelope(), **bodyweight_record_data(request.auth, start, end, program)}


@router.get(
    "/records/personal-bests",
    response=PersonalBestOut,
    tags=["records"],
    summary="Personal bests per exercise with a prior-range comparison",
)
def personal_bests(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: OptFilterParam = StrictQuery(None),
    kind: PersonalBestKind = StrictQuery(None),
):
    validate_date_range(start, end)
    return {
        **envelope(),
        **personal_best_data(request.auth, start, end, program, kind),
    }
