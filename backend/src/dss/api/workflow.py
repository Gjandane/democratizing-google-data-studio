"""Staged artifact endpoints. Code owns edits, validation and stage transitions."""
import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from dss.api.builds import build_response
from dss.api.prototype import current
from dss.artifacts import state as stages
from dss.artifacts import design as design_node
from dss.artifacts.models import Context, Design
from dss.db import new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes import context as node
from dss.harness.nodes import outline as outline_node
from dss.harness.nodes import blueprint as blueprint_node

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
        stages.confirmed(build, 'context', issues)
        existing = outline_node.load(folder)
        if existing is not None:
            async def revalidate(run_id):
                await outline_node.persist(state.harness, build, folder, run_id,
                    outline_node.revalidate(existing, draft), confirm_context=True)
                return 'Outline revalidated. Your questions and selections were kept.'
            accepted = enqueue(state, build_id, 'outline_propose', revalidate)
        else:
            accepted = enqueue(state, build_id, 'outline_propose', {'action': 'outline_propose',
                'build': build, 'config': state.settings.get(), 'folder': folder, 'confirm_context': True})
    state.harness.active_builds.add(build_id)
    return accepted


class SelectionItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    selected: StrictBool


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    questions: list[SelectionItem] = Field(min_length=1, max_length=100)


class OtherText(BaseModel):
    model_config = ConfigDict(extra='forbid')
    section_id: str | None
    text: str = Field(min_length=1, max_length=1000)


class Suggest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    section_id: str


def outline_inputs(state, build, *, section_id=None, require_section=False):
    from dss.api.synthetic_data import invalid_request
    _, folder = current(state, build['id'])
    draft = outline_node.load(folder)
    if not draft or stages.states(build)['context'] != 'confirmed':
        raise stages.wrong_stage(build)
    if (require_section or section_id is not None) and not any(s.id == section_id for s in draft.sections):
        raise invalid_request()
    return folder, draft


@router.get('/{build_id}/outline')
async def get_outline(build_id: str, request: Request):
    _, folder = current(request.app.state, build_id)
    return outline_node.load(folder)


@router.post('/{build_id}/outline/propose', status_code=202)
async def propose_outline(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('outline',)) as build:
        folder, _ = outline_inputs(state, build)
        accepted = enqueue(state, build_id, 'outline_propose', {'action': 'outline_propose',
            'build': build, 'config': state.settings.get(), 'folder': folder})
    state.harness.active_builds.add(build_id)
    return accepted


@router.put('/{build_id}/outline/selection')
async def select_outline(build_id: str, request: Request, body: Selection):
    from dss.api.synthetic_data import invalid_request
    state = request.app.state
    with stages.action(state, build_id) as build:
        stages.require_edit(build, 'outline')
        folder, draft = outline_inputs(state, build)
        choices = {q.id: q.selected for q in body.questions}
        known = {q.id for s in draft.sections for q in s.questions}
        if len(choices) != len(body.questions) or not choices.keys() <= known:
            raise invalid_request()
        for section in draft.sections:
            for question in section.questions:
                question.selected = choices.get(question.id, question.selected)
        return await outline_node.persist(state.harness, build, folder, None, draft)


async def extend_outline(state, build_id, body, action):
    from dss.api.synthetic_data import invalid_request
    from dss.memory import episodic
    with stages.action(state, build_id) as build:
        stages.require_edit(build, 'outline')
        folder, _ = outline_inputs(state, build, section_id=body.section_id, require_section=action == 'outline_suggest')
        payload = {'action': action, 'build': build, 'config': state.settings.get(),
                   'folder': folder, 'section_id': body.section_id}
        if action == 'outline_other':
            if not body.text.strip():
                raise invalid_request()
            message = episodic.save(state.db, build_id, 'user', body.text, action)
            payload['source'] = {'id': message['id'], 'kind': 'message', 'text': message['text'],
                'reference_id': None, 'image_id': None, 'item_id': None, 'component_id': None, 'batch_id': None}
            await state.harness.emit(build_id, None, 'message.done', {'message': message})
        accepted = enqueue(state, build_id, action, payload)
    state.harness.active_builds.add(build_id)
    return accepted


@router.post('/{build_id}/outline/other', status_code=202)
async def other_outline(build_id: str, request: Request, body: OtherText):
    return await extend_outline(request.app.state, build_id, body, 'outline_other')


@router.post('/{build_id}/outline/suggest', status_code=202)
async def suggest_outline(build_id: str, request: Request, body: Suggest):
    return await extend_outline(request.app.state, build_id, body, 'outline_suggest')


@router.post('/{build_id}/outline/confirm')
async def confirm_outline(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('outline',)) as build:
        folder, draft = outline_inputs(state, build)
        selected = sum(q.selected for s in draft.sections for q in s.questions)
        issues = [] if 1 <= selected <= 24 else [{'path': '/sections', 'message': 'Select 1-24 questions'}]
        advanced = {**build, **stages.confirmed(build, 'outline', issues)}
        existing = design_node.load(folder)
        design = (design_node.validate(existing, draft) if existing is not None else
                  design_node.prefill(build, node.load(folder), draft, design_node.reference_style(folder)))
        await design_node.persist(state.harness, advanced, folder, design)
        built = build_response(state.db, state.settings.get(), build_id)
        return built


@router.get('/{build_id}/design/presets')
async def get_design_presets(build_id: str, request: Request):
    current(request.app.state, build_id)
    return design_node.presets()


@router.get('/{build_id}/design')
async def get_design(build_id: str, request: Request):
    _, folder = current(request.app.state, build_id)
    return design_node.load(folder)


def design_inputs(state, build):
    _, folder = current(state, build['id'])
    outline = outline_node.load(folder)
    values = stages.states(build)
    if not outline or any(values[name] != 'confirmed' for name in ('context', 'outline')):
        raise stages.wrong_stage(build)
    return folder, outline


@router.post('/{build_id}/design/prefill')
async def prefill_design(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('design',)) as build:
        folder, outline = design_inputs(state, build)
        draft = design_node.prefill(build, node.load(folder), outline, design_node.reference_style(folder))
        return await design_node.persist(state.harness, build, folder, draft)


@router.put('/{build_id}/design')
async def put_design(build_id: str, request: Request):
    from dss.api.synthetic_data import read_json, invalid_request
    body = await read_json(request)
    if not isinstance(body, dict) or {'revision', 'issues'} & body.keys():
        raise invalid_request()
    try:
        draft = Design.model_validate({**body, 'revision': 1, 'issues': []})
    except ValidationError as exc:
        raise RunError('invalid_request', 'Invalid Design structure', 422, {'issues': [
            {'path': '/' + '/'.join(map(str, e['loc'])), 'message': 'Invalid Design structure: ' + e['type']}
            for e in exc.errors(include_input=False, include_context=False)]}) from None
    state = request.app.state
    with stages.action(state, build_id) as build:
        stages.require_edit(build, 'design')
        folder, outline = design_inputs(state, build)
        return await design_node.persist(state.harness, build, folder, design_node.validate(draft, outline))


@router.post('/{build_id}/design/confirm', status_code=202)
async def confirm_design(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('design',)) as build:
        folder, outline = design_inputs(state, build)
        draft = design_node.load(folder)
        issues = ([i.model_dump() for i in design_node.validate(draft, outline).issues] if draft else
                  [{'path': '', 'message': 'Draft Design first'}])
        transition = stages.confirmed(build, 'design', issues)
        stages.save(state.db, build_id, transition)
        build = {**build, **transition}
        await state.harness.emit(build_id, None, 'stage.changed', {'stage': 'blueprint'})
        accepted = enqueue(state, build_id, 'blueprint', {'build': build, 'folder': folder,
            'config': state.settings.get(), 'factory': state.bigquery_factory})
    state.harness.active_builds.add(build_id)
    return accepted


@router.get('/{build_id}/blueprint')
async def get_blueprint(build_id: str, request: Request):
    _, folder = current(request.app.state, build_id)
    return blueprint_node.load(folder)


@router.post('/{build_id}/blueprint/accept', status_code=202)
async def accept_blueprint(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('blueprint',)) as build:
        folder, _ = design_inputs(state, build)
        draft = blueprint_node.preflight(state.db, build_id, folder)
        transition = stages.confirmed(build, 'blueprint')
        # The prototype branch owns layout/publication and saves this confirmation
        # only after its prototype commits. A rejected run preserves this stage.
        accepted = enqueue(state, build_id, 'prototype', {'build': build, 'folder': folder,
            'blueprint': draft, 'transition': transition, 'config': state.settings.get(),
            'factory': state.bigquery_factory})
    state.harness.active_builds.add(build_id)
    return accepted


@router.post('/{build_id}/blueprint/regenerate', status_code=202)
async def regenerate_blueprint(build_id: str, request: Request):
    state = request.app.state
    with stages.action(state, build_id, ('blueprint', 'prototype')) as build:
        folder, _ = design_inputs(state, build)
        if stages.states(build)['design'] != 'confirmed':
            raise stages.wrong_stage(build)
        transition = stages.edited({**build, 'stage': 'blueprint'}, 'blueprint')
        stages.save(state.db, build_id, transition)
        build = {**build, **transition}
        accepted = enqueue(state, build_id, 'blueprint', {'build': build, 'folder': folder,
            'config': state.settings.get(), 'factory': state.bigquery_factory, 'regenerate': True})
    state.harness.active_builds.add(build_id)
    return accepted
