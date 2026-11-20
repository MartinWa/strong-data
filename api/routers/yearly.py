from ninja import Router

from ..contract import envelope
from ..params import OptDateParam, OptFilterParam, OptIntParam, StrictQuery, validate_year
from ..queries import pace_data, today, yearly_data
from ..schemas import PaceOut, YearlyOut

router = Router()


@router.get("/yearly", response=YearlyOut, tags=["yearly"], summary="Yearly totals")
def yearly(request, program: OptFilterParam = StrictQuery(None)):
    return {**envelope(), **yearly_data(request.auth, program)}


@router.get("/yearly/pace", response=PaceOut, tags=["yearly"], summary="Year-to-date pace")
def yearly_pace(
    request,
    year: OptIntParam = StrictQuery(None),
    as_of: OptDateParam = StrictQuery(None),
    program: OptFilterParam = StrictQuery(None),
):
    reference = as_of or today()
    compared_year = reference.year if year is None else year
    validate_year(compared_year)
    return {**envelope(), **pace_data(request.auth, compared_year, reference, program)}
