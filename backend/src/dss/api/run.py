import asyncio
import json
import subprocess
from fastapi import APIRouter, Request
from dss.api.prototype import current, read_spec
from dss.db import new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes.execute import execute, engine_command
from dss.config import BACKEND_DIR
from dss.harness.nodes.compile import perform as compile_current

router = APIRouter(prefix="/api/builds")


def require_prototype(build):
    if build["stage"] != "prototype":
        raise RunError("wrong_stage", "This action needs a prototype", 409, {"stage": build["stage"]})


@router.post("/{build_id}/recipe")
async def recipe(build_id: str, request: Request):
    state = request.app.state
    build, folder = current(state, build_id)
    require_prototype(build)
    async def perform(run_id):
        text = compile_current(read_spec(folder), build["current_version"], folder)
        def printable():
            result = subprocess.run(engine_command() + ["print", str(folder / "recipe.jsonl")], cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8", timeout=30)
            if result.returncode:
                raise RunError("invalid_recipe", "Engine could not print the recipe", 422)
            return result.stdout.splitlines()
        lines = await asyncio.to_thread(printable)
        ops = [json.loads(line) for line in text.splitlines()[1:]]
        if len(lines) != len(ops):
            raise RunError("invalid_recipe", "Engine print output does not match recipe", 422)
        return json.dumps({"op_count": len(ops), "ops": [{"op_id": op["id"], "line": line} for op, line in zip(ops, lines)]})
    result = await state.harness.run("recipe", build_id, perform)
    return json.loads(result["reply"])


@router.post("/{build_id}/run", status_code=202)
async def run(build_id: str, request: Request):
    state = request.app.state
    build, folder = current(state, build_id)
    if state.engine_busy:
        raise RunError("engine_busy", "Another engine run is in progress", 409)
    require_prototype(build)
    if build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "Another action is running", 409, {"stage": build["stage"]})
    if not (folder / "recipe.jsonl").is_file():
        raise RunError("wrong_stage", "Compile the recipe before running it", 409, {"stage": build["stage"]})
    state.engine_busy = True
    run_id = new_id("r")
    with state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='build',updated_at=? WHERE id=?", (now(), build_id))
    async def perform(actual_run_id):
        await state.harness.emit(build_id, actual_run_id, "stage.changed", {"stage": "build"})
        return await execute(state, build_id, actual_run_id, folder, build["current_version"])
    async def background():
        try:
            await state.harness.run("execute", build_id, perform, run_id=run_id)
        finally:
            state.engine_busy = False
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}
