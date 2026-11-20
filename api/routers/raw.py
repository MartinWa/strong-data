from django.db import transaction
from django.db.models import F
from django.http import Http404
from ninja import Router

from workouts.models import WorkoutSession

from ..contract import envelope
from ..params import (
    IntParam,
    NoQuery,
    OptBoolParam,
    OptDateParam,
    OptFilterParam,
    StrictQuery,
    build_page,
    parse_sort,
    sort_query,
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
    "date": "session__session_date",
    "set_time": "set_time",
    "exercise": "exercise__name",
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


def _order_by(column, descending):
    value = F(column)
    primary = value.desc(nulls_last=True) if descending else value.asc(nulls_first=True)
    return (primary, "id")


def _paginate(request, queryset, serialize, limit, offset, order_by):
    ordered = queryset.order_by(*order_by)
    count = ordered.count()
    items = [serialize(item) for item in ordered[offset : offset + limit]]
    return {**envelope(), **build_page(request, items, count, limit, offset)}


@router.get("/sessions", response=SessionPage, tags=["raw"], summary="Paginated sessions")
def sessions(
    request,
    start: OptDateParam = StrictQuery(None),
    end: OptDateParam = StrictQuery(None),
    program: OptFilterParam = StrictQuery(None),
    exercise: str | None = StrictQuery(None),
    muscle: str | None = StrictQuery(None),
    weighted: OptBoolParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
    offset: IntParam = StrictQuery(0),
    sort: str | None = sort_query(SESSION_SORT_KEYS, "date"),
):
    key, descending = _filters(
        start, end, limit, offset, sort, SESSION_SORT_FIELDS, SESSION_SORT_KEYS, "date"
    )
    queryset = owned_sessions(
        request.auth,
        start=start,
        end=end,
        program=program,
        exercise=exercise,
        muscle=muscle,
        weighted=weighted,
    )
    return _paginate(
        request,
        queryset,
        lambda session: public_session(session_record(session)),
        limit,
        offset,
        _order_by(key, descending),
    )


@router.get("/sessions/{id}", response=SessionDetailOut, tags=["raw"], summary="Session detail")
def session_detail(request, id: IntParam, query: NoQuery = StrictQuery(None)):
    with transaction.atomic():
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
    program: OptFilterParam = StrictQuery(None),
    exercise: str | None = StrictQuery(None),
    muscle: str | None = StrictQuery(None),
    weighted: OptBoolParam = StrictQuery(None),
    limit: IntParam = StrictQuery(50),
    offset: IntParam = StrictQuery(0),
    sort: str | None = sort_query(SET_SORT_KEYS, "set_time"),
):
    key, descending = _filters(
        start, end, limit, offset, sort, SET_SORT_FIELDS, SET_SORT_KEYS, "set_time"
    )
    mapping = muscle_map(request.auth)
    queryset = owned_sets(
        request.auth,
        start=start,
        end=end,
        program=program,
        exercise=exercise,
        muscle=muscle,
        weighted=weighted,
    )
    return _paginate(
        request,
        queryset,
        lambda item: public_set(set_record(item, mapping)),
        limit,
        offset,
        _order_by(key, descending),
    )


@router.get(
    "/exercises/{path:name}/sets",
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
    sort: str | None = sort_query(SET_SORT_KEYS, "set_time"),
):
    key, descending = _filters(
        start, end, limit, offset, sort, SET_SORT_FIELDS, SET_SORT_KEYS, "set_time"
    )
    mapping = muscle_map(request.auth)
    queryset = owned_sets(request.auth, start=start, end=end, exercise=name)
    return _paginate(
        request,
        queryset,
        lambda item: public_set(set_record(item, mapping)),
        limit,
        offset,
        _order_by(key, descending),
    )
