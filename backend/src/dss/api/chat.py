"""Stateless interview actions, with replies delivered on the build event stream."""
import asyncio
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from dss.api.builds import require_build
from dss.db import new_id
from dss.harness.guardrails import RunError
from dss.memory import episodic

router = APIRouter(prefix="/api/builds")


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=24000)


def require_stage(state, build_id, expected):
    require_build(state.db, build_id)
    with state.db.connect() as conn:
        stage = conn.execute("SELECT stage FROM builds WHERE id=?", (build_id,)).fetchone()[0]
    if stage != expected or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "Interview action is unavailable in this stage", 409, {"stage": stage})


async def launch(state, build_id, text, start=False):
    require_stage(state, build_id, "connect" if start else "interview")
    run_id = new_id("r")
    message = None if start else episodic.save(state.db, build_id, "user", text)
    # Reserve before yielding so a second request cannot save another user message.
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run("interview", build_id,
                {"text": text, "start": start, "config": state.settings.get()},
                run_id=run_id, reserved=True)
        except RunError:
            pass  # The harness has persisted the trace and emitted run.finished(error).

    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id, **({"message_id": message["id"]} if message else {})}


@router.post("/{build_id}/interview/start", status_code=202)
async def start(build_id: str, request: Request):
    return await launch(request.app.state, build_id, "Start the interview with one question grounded in the data profile.", True)


@router.post("/{build_id}/messages", status_code=202)
async def turn(build_id: str, body: Turn, request: Request):
    if not body.text.strip():
        raise RunError("invalid_request", "Message must contain text", 422)
    return await launch(request.app.state, build_id, body.text)


@router.post("/{build_id}/plan", status_code=202)
async def plan(build_id: str, request: Request):
    state = request.app.state
    require_build(state.db, build_id)
    with state.db.connect() as conn:
        stage = conn.execute("SELECT stage FROM builds WHERE id=?", (build_id,)).fetchone()[0]
    if stage not in ("interview", "prototype") or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "Planning is unavailable in this stage", 409, {"stage": stage})
    run_id = new_id("r")
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run("plan", build_id,
                {"config": state.settings.get(), "factory": state.bigquery_factory},
                run_id=run_id, reserved=True)
        except RunError:
            pass

    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}


@router.get("/{build_id}/messages")
def history(build_id: str, request: Request):
    require_build(request.app.state.db, build_id)
    return episodic.messages(request.app.state.db, build_id)
