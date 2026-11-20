from ninja import Router

from ..contract import envelope
from ..params import OptDateParam, OptFilterParam, StrictQuery, validate_date_range
from ..queries import summary_data
from ..schemas import SummaryOut

router = Router()


@router.get("/summary", response=SummaryOut, tags=["summary"], summary="Summary statistics")
def summary(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: OptFilterParam = StrictQuery(None),
):
    validate_date_range(start, end)
    return {
        **envelope(),
        **summary_data(request.auth, start, end, program),
    }
