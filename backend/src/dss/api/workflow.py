"""Staged artifact endpoints. Code owns edits, validation and stage transitions."""
import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dss.api.builds import build_response
from dss.api.prototype import current
from dss.artifacts import state as stages
from dss.artifacts.models import Context
from dss.db import new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes import context as node

router = APIRouter(prefix='/api/builds')


class DraftContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: str = Field(default='', max_length=4000)


def enqueue(state, build_id, action, payload):
    """Caller already holds action(); reservation transfers to the background run."""
    run_id = new_id('r')
    async def background():
        try:
            await state.harness.run(action, build_id, payload, run_id=run_id, reserved=True)
        except RunError:
            pass  # harness persists the sanitized run.finished and trace
        finally:
            state.harness.active_builds.discard(build_id)
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {'run_id': run_id}


@router.get('/{build_id}/context')
async def get_context(build_id: str, request: Request):
    _, folder = current(request.app.state, build_id)
    return node.load(folder)


@router.post('/{build_id}/context', status_code=202)
async def draft_context(build_id: str, request: Request, body: DraftContext = DraftContext()):
    state = request.app.state
    with stages.action(state, build_id, ('connect', 'context')) as build:
        if not node.sources(state.db, build_id):
            raise stages.wrong_stage(build)
        notes = body.notes if 'notes' in body.model_fields_set else build.get('notes')
        with state.db.connect() as conn:
            conn.execute('UPDATE builds SET notes=?,stage=?,updated_at=? WHERE id=?', (notes, 'context', now(), build_id))
        build = {**build, 'notes': notes, 'stage': 'context'}
        _, folder = current(state, build_id)
        accepted = enqueue(state, build_id, 'context', {'build': build, 'config': state.settings.get(),
                           'folder': folder, 'factory': state.bigquery_factory})
    # action() released its lexical reservation; no await occurs before transfer.
    state.harness.active_builds.add(build_id)
    return accepted


@router.put('/{build_id}/context')
async def put_context(build_id: str, request: Request):
    # Parse before acquiring the reservation; a slow client cannot own a build.
    from dss.api.synthetic_data import read_json, invalid_request
    body = await read_json(request)
    if not isinstance(body, dict) or {'revision', 'issues'} & body.keys():
        raise invalid_request()
    try:
        draft = Context.model_validate({**body, 'revision': 1, 'issues': []})
    except ValidationError as exc:
        raise RunError('invalid_request', 'Invalid Context structure', 422, {'issues': [
            {'path': '/' + '/'.join(map(str, e['loc'])), 'message': 'Invalid Context structure: ' + e['type']}
            for e in exc.errors(include_input=False, include_context=False)]}) from None
    state = request.app.state
    with stages.action(state, build_id) as build:
        stages.require_edit(build, 'context')
        if not node.sources(state.db, build_id):
            raise stages.wrong_stage(build)
        _, folder = current(state, build_id)
        draft = await asyncio.to_thread(node.validate, draft, node.sources(state.db, build_id),
                                        lambda: state.bigquery_factory(state.settings.get()))
        return await node.persist(state.harness, build, folder, None, draft)


@router.post('/{build_id}/context/confirm', status_code=202)
async def confirm_context(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('context',)) as build:
        _, folder = current(state, build_id)
        draft = node.load(folder)
        issues = [i.model_dump() for i in draft.issues] if draft else [{'path': '', 'message': 'Draft Context first'}]
        transition = stages.confirmed(build, 'context', issues)

        async def finish(run_id):
            stages.save(state.db, build_id, transition)
            await state.harness.emit(build_id, run_id, 'stage.changed', {'stage': 'outline'})
            await state.harness.emit(build_id, run_id, 'build.updated', {
                'build': build_response(state.db, state.settings.get(), build_id)})
            return 'Context confirmed. Continue with the dashboard outline.'
        # Task 15.4 adds the Outline model branch to this accepted action.
        accepted = enqueue(state, build_id, 'outline_propose', finish)
    state.harness.active_builds.add(build_id)
    return accepted
