"""Agent-only transport, authenticated independently of the shared access code."""
from fastapi import APIRouter, Depends, Request, Response, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from dss.agent.jobs import safe_file
from dss.api.session import matches
from dss.harness.guardrails import RunError


async def require_agent(request: Request):
    config = request.app.state.config
    if config.engine_mode != "agent":
        raise RunError("agent_mode_off", "Build agent mode is disabled", 404)
    token = config.agent_token.get_secret_value()
    if not token or not matches(request.headers.get("x-dss-agent-token", ""), token):
        raise RunError("agent_unauthorized", "Build agent token required", 401)


router = APIRouter(prefix="/api/agent", dependencies=[Depends(require_agent)])


class Heartbeat(BaseModel):
    chrome_running: bool
    signed_in: bool
    agent_version: str


class Events(BaseModel):
    events: list[dict] = Field(min_length=1)


class Finished(BaseModel):
    exit_code: int
    stderr_tail: str


@router.post("/heartbeat")
async def heartbeat(body: Heartbeat, request: Request):
    request.app.state.agent_jobs.heartbeat(body.chrome_running, body.signed_in)
    return {"ok": True}


@router.get("/jobs/next")
async def next_job(request: Request, wait: float = Query(default=25, ge=0, le=25)):
    data = await request.app.state.agent_jobs.next(wait)
    return data if data else Response(status_code=204)


@router.get("/jobs/{run_id}/files/{name:path}")
async def download(run_id: str, name: str, request: Request):
    job = request.app.state.agent_jobs.get(run_id)
    safe_file(job.folder, name)
    if name not in job.inputs:
        raise RunError("invalid_name", "File is not a job input", 400)
    source = job.inputs[name]
    if isinstance(source, bytes):  # the job's packaged recipe copy
        return Response(source, media_type="application/octet-stream")
    if not source.is_file():
        raise RunError("invalid_name", "Job input is unavailable", 400)
    return FileResponse(source)


@router.post("/jobs/{run_id}/events")
async def events(run_id: str, body: Events, request: Request):
    await request.app.state.agent_jobs.events(run_id, body.events)
    return {"ok": True}


@router.put("/jobs/{run_id}/screens/{file:path}")
async def screen(run_id: str, file: str, request: Request):
    manager = request.app.state.agent_jobs
    job = manager.get(run_id)
    # Validate before consuming the body, then recheck under the job's lock.
    root = job.folder / "screens"
    safe_file(root, file)
    if root.resolve().parent != job.folder.resolve() or not file.endswith(".png"):
        raise RunError("invalid_name", "Invalid screenshot name", 400)
    content = await request.body()
    async with job.lock:
        manager.get(run_id)
        target = safe_file(root, file)
        root.mkdir(exist_ok=True)
        target.write_bytes(content)
    return {"ok": True}


@router.post("/jobs/{run_id}/finished")
async def finished(run_id: str, body: Finished, request: Request):
    # stderr is deliberately not persisted or logged: it can contain credentials.
    await request.app.state.agent_jobs.finish(run_id, body.exit_code)
    return {"ok": True}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def unknown():
    raise RunError("job_not_found", "Agent route not found", 404)
