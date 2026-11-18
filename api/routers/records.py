from ninja import Router

from ..contract import envelope
from ..queries import bodyweight_record_data, est_1rm_record_data
from ..schemas import BodyweightRecordOut, Est1rmRecordOut

router = Router()


@router.get(
    "/records/est-1rm",
    response=Est1rmRecordOut,
    tags=["records"],
    summary="Best estimated 1RM per exercise",
)
def est_1rm_records(request):
    return {**envelope(), **est_1rm_record_data(request.auth)}


@router.get(
    "/records/bodyweight",
    response=BodyweightRecordOut,
    tags=["records"],
    summary="Best bodyweight set per exercise",
)
def bodyweight_records(request):
    return {**envelope(), **bodyweight_record_data(request.auth)}
