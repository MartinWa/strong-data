from ninja import Router

from ..contract import envelope
from ..params import IntParam, OptDateParam, StrictQuery
from ..queries import pace_data, today, yearly_data
from ..schemas import PaceOut, YearlyOut

router = Router()


@router.get("/yearly", response=YearlyOut, tags=["yearly"], summary="Yearly totals")
def yearly(request):
    return {**envelope(), **yearly_data(request.auth)}


@router.get("/yearly/pace", response=PaceOut, tags=["yearly"], summary="Year-to-date pace")
def yearly_pace(
    request,
    year: IntParam = StrictQuery(0),
    as_of: OptDateParam = StrictQuery(None),
):
    reference = as_of or today()
    compared_year = year or reference.year
    return {**envelope(), **pace_data(request.auth, compared_year, reference)}
