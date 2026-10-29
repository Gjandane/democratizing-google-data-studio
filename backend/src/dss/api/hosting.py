"""How this deployment hosts builds (api.md 3.4 `Hosting`), read from the startup config."""
from fastapi import APIRouter, Request

from dss.agent.jobs import API_VERSION

router = APIRouter(prefix="/api")


@router.get("/hosting")
def hosting(request: Request):
    config = request.app.state.config
    return {"mode": config.engine_mode, "public": config.open_link, "locked_sources": config.locked_sources,
            "share_data": config.share_data, "api_version": API_VERSION}
