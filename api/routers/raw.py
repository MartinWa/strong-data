from django.http import Http404
from ninja import Router

from workouts.models import WorkoutSession

from ..contract import envelope
from ..params import (
    IntParam,
    OptBoolParam,
    OptDateParam,
    StrictQuery,
    build_page,
    parse_sort,
    validate_date_range,
    validate_pagination,
)
from ..queries import (
    SESSION_SORT_KEYS,
    SET_SORT_KEYS,
    muscle_map,
    owned_sessions,
    owned_sets,
    public_session,
    public_set,
    session_record,
    set_record,
    sort_records,
)
from ..schemas import SessionDetailOut, SessionPage, SetPage

router = Router()

SESSION_SORT_FIELDS = {
    "date": "session_date",
    "program": "program",
    "workout_name": "workout_name",
    "start_time": "start_time",
    "volume": "total_volume_kg",
    "sets": "set_count",
}

SET_SORT_FIELDS = {
    "date": "session_date",
    "set_time": "set_time",
    "exercise": "exercise",
    "set_order": "set_order",
    "weight": "weight_kg",
    "reps": "reps",
    "rpe": "rpe",
    "volume": "volume_kg",
    "est_1rm": "est_1rm_kg",
}


def _filters(start, end, limit, offset, sort, fields, allowed, default):
    validate_date_range(start, end)
    validate_pagination(limit, offset)
    key, descending = parse_sort(sort, allowed, default)
    return fields[key], descending


def _paginate(request, records, serializer, limit, offset, key, descending):
    ordered = sort_records(records, key, descending)
    page = build_page(
        request,
        [serializer(record) for record in ordered[offset : offset + limit]],
        len(ordered),
        limit,
        offset,
    )
    return {**envelope(), **page}


@router.get("/sessions", response=SessionPage, tags=["raw"], summary="Paginated sessions")
def sessions(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: str | None = StrictQuery(None),
    exercise: str | None = StrictQuery(None),
    muscle: str | None = StrictQuery(None),
    weighted: OptBoolParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
    offset: IntParam = StrictQuery(0),
    sort: str | None = StrictQuery(None),
):
    key, descending = _filters(
        start, end, limit, offset, sort, SESSION_SORT_FIELDS, SESSION_SORT_KEYS, "date"
    )
    records = [
        session_record(session)
        for session in owned_sessions(
            request.auth,
            start=start,
            end=end,
            program=program,
            exercise=exercise,
            muscle=muscle,
            weighted=weighted,
        )
    ]
    return _paginate(request, records, public_session, limit, offset, key, descending)


@router.get("/sessions/{id}", response=SessionDetailOut, tags=["raw"], summary="Session detail")
def session_detail(request, id: IntParam):
    session = WorkoutSession.objects.filter(owner=request.auth, pk=id).first()
    if session is None:
        raise Http404("Session not found")
    mapping = muscle_map(request.auth)
    sets = [
        public_set(set_record(item, mapping))
        for item in session.sets.select_related("exercise").order_by("set_time", "set_order")
    ]
    return {**envelope(), **public_session(session_record(session)), "sets": sets}


@router.get("/sets", response=SetPage, tags=["raw"], summary="Paginated sets")
def sets(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: str | None = StrictQuery(None),
    exercise: str | None = StrictQuery(None),
    muscle: str | None = StrictQuery(None),
    weighted: OptBoolParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
    offset: IntParam = StrictQuery(0),
    sort: str | None = StrictQuery(None),
):
    key, descending = _filters(
        start, end, limit, offset, sort, SET_SORT_FIELDS, SET_SORT_KEYS, "set_time"
    )
    mapping = muscle_map(request.auth)
    records = [
        set_record(item, mapping)
        for item in owned_sets(
            request.auth,
            start=start,
            end=end,
            program=program,
            exercise=exercise,
            muscle=muscle,
            weighted=weighted,
        )
    ]
    return _paginate(request, records, public_set, limit, offset, key, descending)


@router.get(
    "/exercises/{name}/sets",
    response=SetPage,
    tags=["raw"],
    summary="Paginated set history for one exercise",
)
def exercise_sets(
    request,
    name: str,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
    offset: IntParam = StrictQuery(0),
    sort: str | None = StrictQuery(None),
):
    key, descending = _filters(
        start, end, limit, offset, sort, SET_SORT_FIELDS, SET_SORT_KEYS, "set_time"
    )
    mapping = muscle_map(request.auth)
    records = [
        set_record(item, mapping)
        for item in owned_sets(request.auth, start=start, end=end, exercise=name)
    ]
    return _paginate(request, records, public_set, limit, offset, key, descending)
