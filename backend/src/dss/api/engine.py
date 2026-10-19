"""Local engine health and interactive sign-in."""
import asyncio
import json
import subprocess
import os
import threading

from fastapi import APIRouter, Request
from dss.config import BACKEND_DIR
from dss.db import new_id
from dss.harness.guardrails import RunError
from dss.harness.nodes.execute import engine_command, terminate_tree

router = APIRouter(prefix="/api/engine")
trace_router = APIRouter()


@trace_router.get("/api/traces")
def traces(request: Request, build_id: str | None = None):
    with request.app.state.db.connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT run_id,build_id,node,model,input_tokens,output_tokens,latency_ms,tool_calls,status,error,started_at "
            "FROM traces WHERE (? IS NULL OR build_id=?) ORDER BY started_at DESC,rowid DESC", (build_id, build_id))]


async def control_command(command, timeout):
    """Keep the process tree owned until completion, even on task cancellation."""
    cancelled = threading.Event()
    processes = []
    def worker():
        process = subprocess.Popen(engine_command() + [command], cwd=BACKEND_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=os.name != "nt")
        processes.append(process)
        try:
            if cancelled.is_set():
                terminate_tree(process)
            output, _ = process.communicate(timeout=timeout)
            return process.returncode, output
        finally:
            if process.poll() is None:
                terminate_tree(process)
            process.wait()
            process.stdout.close()
    task = asyncio.create_task(asyncio.to_thread(worker))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        if processes:
            await asyncio.to_thread(terminate_tree, processes[0])
        try:
            await task
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise


@router.get("/status")
async def status(request: Request):
    state = request.app.state
    if state.engine_busy:
        data = getattr(state, "engine_status", {"chrome_running": False, "signed_in": False})
    else:
        state.engine_busy = True
        try:
            try:
                code, output = await control_command("check", 30)
                value = json.loads(output) if code == 0 else {}
                data = {key: isinstance(value, dict) and value.get(key) is True
                        for key in ("chrome_running", "signed_in")}
            except (OSError, ValueError, subprocess.TimeoutExpired):
                data = {"chrome_running": False, "signed_in": False}
            state.engine_status = data
        finally:
            state.engine_busy = False
    return {"mode": "local", **data, "agent_connected": False, "agent_last_seen": None}


@router.post("/login", status_code=202)
async def login(request: Request):
    state = request.app.state
    if state.engine_busy:
        raise RunError("engine_busy", "Another engine action is in progress", 409)
    state.engine_busy = True
    run_id = new_id("r")
    async def perform(actual_run_id):
        try:
            code, _ = await control_command("login", 310)
        except (OSError, subprocess.TimeoutExpired):
            raise RunError("engine_not_signed_in", "Engine sign-in did not finish", 424) from None
        if code:
            raise RunError("engine_not_signed_in", "Engine sign-in did not finish", 424)
        return "Engine sign-in finished"
    async def background():
        try:
            await state.harness.run("engine_login", None, perform, run_id=run_id)
        except RunError:
            pass
        finally:
            state.engine_busy = False
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}
