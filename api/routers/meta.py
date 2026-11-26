from django.db import connection
from ninja import Router

from ..contract import ServiceUnavailableError, envelope
from ..params import NoQuery, StrictQuery
from ..schemas import HealthOut, MeOut

router = Router()


@router.get("/healthz", auth=None, response=HealthOut, tags=["meta"], summary="Liveness probe")
def healthz(request, query: NoQuery = StrictQuery(None)):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:
        raise ServiceUnavailableError() from exc
    return {**envelope(), "status": "ok"}


@router.get("/me", response=MeOut, tags=["meta"], summary="Token identity")
def me(request, query: NoQuery = StrictQuery(None)):
    user = request.auth
    return {**envelope(), "id": user.id, "username": user.username}
