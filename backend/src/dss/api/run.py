import asyncio
import json
from fastapi import APIRouter, Request
from dss.api.prototype import current, read_spec
from dss.db import new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes.execute import execute
from dss.harness.nodes.compile import perform as compile_current
from dss.recipe.compiler import compile_recipe, preview

router = APIRouter(prefix="/api/builds")


def require_prototype(build):
    if build["stage"] != "prototype":
        raise RunError("wrong_stage", "This action needs a prototype", 409, {"stage": build["stage"]})


def refresh(folder, version):
    """Recompile from the current spec; a failure keeps the previous complete recipe."""
    try:
        spec = read_spec(folder)
    except ValueError:
        raise RunError("invalid_recipe", "Spec could not be compiled into a recipe", 422) from None
    compile_current(spec, version, folder)


@router.post("/{build_id}/recipe")
async def recipe(build_id: str, request: Request):
    state = request.app.state
    build, folder = current(state, build_id)
    require_prototype(build)
    # An agent job keeps serving this folder's files until it is released.
    if any(job.data["build_id"] == build_id for job in state.agent_jobs.running.values()):
        raise RunError("wrong_stage", "A build is still running for this version", 409, {"stage": build["stage"]})
    async def perform(run_id):
        # Preview in code (never the engine): hosted agent mode has none. Preview before
        # publishing so a failure leaves the previous recipe in place.
        spec, version = read_spec(folder), build["current_version"]
        try:
            ops = preview(compile_recipe(spec, version))
        except Exception:
            raise RunError("invalid_recipe", "Spec could not be compiled into a recipe", 422) from None
        compile_current(spec, version, folder)
        return json.dumps({"op_count": len(ops), "ops": ops})
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
    agent_mode = state.config.engine_mode == "agent"
    if agent_mode and not state.agent_jobs.connected:
        raise RunError("agent_offline", "Start the build agent before building", 424)
    # Revisions and replans replace spec.json without recompiling. Refresh synchronously before
    # any reservation: no await separates the checks above from the lock, and a failure starts
    # nothing and leaves stage, locks and the previous recipe as they were.
    refresh(folder, build["current_version"])
    run_id = new_id("r")
    job = state.agent_jobs.prepare(run_id, build_id, folder, build["current_version"]) if agent_mode else None
    with state.db.connect() as conn:
        conn.execute("UPDATE versions SET status='building' WHERE build_id=? AND n=?", (build_id, build["current_version"]))
        conn.execute("UPDATE builds SET stage='build',updated_at=? WHERE id=?", (now(), build_id))
    state.engine_busy = True
    state.harness.active_builds.add(build_id)
    if job:
        await state.agent_jobs.enqueue(job)
    async def perform(actual_run_id):
        await state.harness.emit(build_id, actual_run_id, "stage.changed", {"stage": "build"})
        return await execute(state, build_id, actual_run_id, folder, build["current_version"])
    async def background():
        try:
            await state.harness.run("execute", build_id, perform, run_id=run_id, reserved=True)
        except RunError:
            pass
        finally:
            try:
                if job:
                    await state.agent_jobs.release(job)
            finally:
                state.engine_busy = False
                state.harness.active_builds.discard(build_id)
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}
