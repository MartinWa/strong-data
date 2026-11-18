from ninja import Router

from ..contract import envelope
from ..schemas import HealthOut, MeOut

router = Router()


@router.get("/healthz", auth=None, response=HealthOut, tags=["meta"], summary="Liveness probe")
def healthz(request):
    return {**envelope(), "status": "ok"}


@router.get("/me", response=MeOut, tags=["meta"], summary="Token identity")
def me(request):
    user = request.auth
    return {**envelope(), "id": user.id, "username": user.username}
