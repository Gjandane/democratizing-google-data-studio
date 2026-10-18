"""Dev-only fixed fixture intake, mounted only with DSS_DEV=1."""
import json
from pathlib import Path
from fastapi import APIRouter, Request
from dss.api.prototype import current
from dss.api.builds import build_response
from dss.db import now
from dss.harness.guardrails import RunError
from dss.render.prototype import render
from dss.spec.models import DashboardSpec

router = APIRouter(prefix="/api/dev/builds")


@router.post("/{build_id}/load-spec")
async def load_spec(build_id: str, request: Request):
    state = request.app.state
    build, folder = current(state, build_id)
    if build["stage"] == "build":
        raise RunError("wrong_stage", "Build is running", 409, {"stage": "build"})
    async def perform(run_id):
        fixture = Path(__file__).resolve().parents[3] / "tests/data/thin_spec.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        data["build_id"] = build_id
        spec = DashboardSpec.model_validate(data)
        html = render(spec)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        (folder / "prototype.html").write_text(html, encoding="utf-8")
        with state.db.connect() as conn:
            conn.execute("UPDATE builds SET stage='prototype',updated_at=? WHERE id=?", (now(), build_id))
            conn.execute("UPDATE versions SET spec_version=?,status='draft' WHERE build_id=? AND n=?", (spec.spec_version, build_id, build["current_version"]))
        await state.harness.emit(build_id, run_id, "stage.changed", {"stage": "prototype"})
        await state.harness.emit(build_id, run_id, "prototype.updated", {"spec_version": spec.spec_version})
        return "Fixture loaded"
    await state.harness.run("load_spec", build_id, perform)
    return build_response(state.db, state.settings.get(), build_id)
