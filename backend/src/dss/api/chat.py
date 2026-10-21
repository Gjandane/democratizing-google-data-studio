"""Read-only assistant explanations, refusals and revision outcomes."""
from fastapi import APIRouter, Request
from dss.api.builds import require_build
from dss.memory import episodic

router = APIRouter(prefix="/api/builds")


@router.get("/{build_id}/messages")
def history(build_id: str, request: Request):
    require_build(request.app.state.db, build_id)
    return episodic.messages(request.app.state.db, build_id)
