import json
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from typing import Literal
from dss.api.builds import require_build
from dss.harness.guardrails import RunError
from dss.render.prototype import render
from dss.spec.models import DashboardSpec

router = APIRouter(prefix="/api/builds")


def current(state, build_id):
    require_build(state.db, build_id)
    with state.db.connect() as conn:
        build = dict(conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone())
    folder = state.settings.get().data_dir / "builds" / build_id / f'v{build["current_version"]}'
    return build, folder


def read_spec(folder):
    if not (folder / "spec.json").is_file():
        raise RunError("wrong_stage", "Load a spec before this action", 409)
    return DashboardSpec.model_validate_json((folder / "spec.json").read_text(encoding="utf-8"))


@router.get("/{build_id}/prototype", response_class=HTMLResponse)
def prototype(build_id: str, request: Request, layer: Literal["all", "decoration"] | None = Query(default=None)):
    _, folder = current(request.app.state, build_id)
    return render(read_spec(folder), layer=layer)


@router.get("/{build_id}/spec")
def spec(build_id: str, request: Request):
    _, folder = current(request.app.state, build_id)
    return read_spec(folder).model_dump()
