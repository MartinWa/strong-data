from typing import Literal

from ninja import Router

from ..contract import envelope
from ..params import OptBoolParam, OptDateParam, StrictQuery, validate_date_range
from ..queries import series_data
from ..schemas import SeriesOut

router = Router()

Bucket = Literal["day", "week", "month", "year"]
GroupBy = Literal["program", "muscle", "exercise"] | None


def _build(request, metric, bucket, group_by, start, end, moving_average):
    validate_date_range(start, end)
    return {
        **envelope(),
        **series_data(request.auth, metric, bucket, group_by, start, end, moving_average),
    }


@router.get("/series/sessions", response=SeriesOut, tags=["series"], summary="Session time series")
def series_sessions(
    request,
    bucket: Bucket = StrictQuery("week"),
    group_by: GroupBy = StrictQuery(None),
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    moving_average: OptBoolParam = StrictQuery(False),
):
    return _build(request, "sessions", bucket, group_by, start, end, moving_average)


@router.get("/series/volume", response=SeriesOut, tags=["series"], summary="Volume time series")
def series_volume(
    request,
    bucket: Bucket = StrictQuery("week"),
    group_by: GroupBy = StrictQuery(None),
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    moving_average: OptBoolParam = StrictQuery(False),
):
    return _build(request, "volume", bucket, group_by, start, end, moving_average)


@router.get(
    "/series/volume-per-session",
    response=SeriesOut,
    tags=["series"],
    summary="Volume per session time series",
)
def series_volume_per_session(
    request,
    bucket: Bucket = StrictQuery("week"),
    group_by: GroupBy = StrictQuery(None),
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    moving_average: OptBoolParam = StrictQuery(False),
):
    return _build(request, "volume-per-session", bucket, group_by, start, end, moving_average)


@router.get(
    "/series/training-time", response=SeriesOut, tags=["series"], summary="Training time series"
)
def series_training_time(
    request,
    bucket: Bucket = StrictQuery("week"),
    group_by: GroupBy = StrictQuery(None),
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    moving_average: OptBoolParam = StrictQuery(False),
):
    return _build(request, "training-time", bucket, group_by, start, end, moving_average)
