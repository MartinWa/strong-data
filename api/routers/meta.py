from ninja import Router

from workouts.models import WorkoutSession

from ..contract import ServiceUnavailableError, envelope
from ..params import NoQuery, StrictQuery
from ..schemas import HealthOut, MeOut

router = Router()


@router.get("/healthz", auth=None, response=HealthOut, tags=["meta"], summary="Readiness probe")
def healthz(request, query: NoQuery = StrictQuery(None)):
    try:
        WorkoutSession.objects.values("id").first()
    except Exception as exc:
        raise ServiceUnavailableError() from exc
    return {**envelope(), "status": "ok"}


@router.get("/me", response=MeOut, tags=["meta"], summary="Token identity")
def me(request, query: NoQuery = StrictQuery(None)):
    user = request.auth
    return {**envelope(), "id": user.id, "username": user.username}
