"""Feasibility recovery action; GET never starts model work."""
import asyncio
from contextlib import contextmanager

from fastapi import APIRouter, Request, Query

from dss.api.prototype import current, read_spec
from dss.db import new_id
from dss.harness.guardrails import RunError
from dss.spec import requirements as req
from dss.spec.capabilities import Checker, load_registry

router = APIRouter(prefix="/api/builds")


@contextmanager
def action(state, build_id):
    build, folder = current(state, build_id)
    if build["stage"] not in ("connect", "context", "outline", "design", "blueprint", "prototype") or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "Feasibility changes need an idle connect through prototype build", 409,
                       {"stage": build["stage"]})
    state.harness.active_builds.add(build_id)
    try:
        yield folder, req.inputs(state.db, build_id, folder), req.load(folder), Checker(load_registry())
    finally:
        state.harness.active_builds.discard(build_id)


@router.post("/{build_id}/feasibility/decisions")
async def decisions(build_id: str, body: req.Decisions, request: Request):
    with action(request.app.state, build_id) as (folder, snapshot, ledger, checker):
        updated, assessment = req.decide(snapshot, ledger, checker, body)
        req.save(folder, updated, assessment)
        return assessment.model_dump()


@router.delete("/{build_id}/feasibility/pending-comments")
async def abandon_comments(build_id: str, request: Request, assessment_id: str = Query(min_length=1)):
    with action(request.app.state, build_id) as (folder, snapshot, ledger, checker):
        req.require_current(snapshot, ledger, checker, assessment_id)
        updated = req.abandon_pending(ledger)
        updated.verification = req.verification(snapshot, updated, checker)
        assessment = req.evaluate(snapshot, updated, checker)
        req.save(folder, updated, assessment)
        return assessment.model_dump()


@router.post("/{build_id}/feasibility/reapply", status_code=202)
async def reapply(build_id: str, body: req.Reapply, request: Request):
    state = request.app.state
    build, folder = current(state, build_id)
    if build['stage'] != 'prototype' or build_id in state.harness.active_builds:
        raise RunError('wrong_stage', 'Reapply requires an idle prototype', 409, {'stage': build['stage']})
    read_spec(folder)
    batch = req.validate_reapply(req.inputs(state.db, build_id, folder), req.load(folder), Checker(load_registry()), body)
    run_id, config = new_id('r'), state.settings.get()
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run('revise', build_id, {'comments': [c.model_dump() for c in batch.comments],
                'config': config, 'factory': state.bigquery_factory, '_reapply': body}, run_id=run_id, reserved=True)
        except RunError:
            pass
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {'run_id': run_id}


@router.get("/{build_id}/feasibility")
async def get_feasibility(build_id: str, request: Request):
    state = request.app.state
    _, folder = current(state, build_id)
    return req.get(req.inputs(state.db, build_id, folder), req.load(folder), Checker(load_registry())).model_dump()


@router.post("/{build_id}/feasibility/check", status_code=202)
async def check_feasibility(build_id: str, request: Request):
    state = request.app.state
    build, _ = current(state, build_id)
    if build["stage"] not in ("connect", "context", "outline", "design", "blueprint", "prototype") or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "Feasibility checks need an idle connect through prototype build", 409,
                       {"stage": build["stage"]})
    if await request.body():
        raise RunError("invalid_request", "Feasibility check takes an empty body", 422)
    # Re-check after the body await, then reserve without yielding.
    build, _ = current(state, build_id)
    if build["stage"] not in ("connect", "context", "outline", "design", "blueprint", "prototype") or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "An action is already running for this build", 409, {"stage": build["stage"]})
    run_id = new_id("r")
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run("capability_check", build_id, {"config": state.settings.get()}, run_id=run_id, reserved=True)
        except RunError:
            pass
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}
