import json
import asyncio
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from typing import Literal
from dss.api.builds import require_build
from dss.harness.guardrails import RunError
from dss.render.prototype import render, aggregate_sql
from hashlib import sha256
from dss.spec.models import DashboardSpec
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from dss.db import new_id
from dss.harness.guardrails import check_reply
from dss.memory import episodic

router = APIRouter(prefix="/api/builds")


class Comment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    component_id: str = Field(pattern=r'^p[1-9][0-9]*_[a-z][a-z0-9]*(?:_[a-z0-9]+)*$')
    text: str = Field(min_length=1, max_length=4000, pattern=r'\S')


class Comments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    comments: list[Comment] = Field(min_length=1, max_length=20)


def current(state, build_id):
    require_build(state.db, build_id)
    with state.db.connect() as conn:
        build = dict(conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone())
    folder = state.settings.get().data_dir / "builds" / build_id / f'v{build["current_version"]}'
    return build, folder


def mutation_current(state, build_id):
    """Recheck after body intake/decoding, immediately before the route reserves the build."""
    episodic.require_no_brief_review(state.db, build_id)
    return current(state, build_id)


def read_spec(folder, *, db=None, build_id=None):
    if not (folder / "spec.json").is_file():
        raise RunError("wrong_stage", "Load a spec before this action", 409)
    document = DashboardSpec.model_validate_json((folder / "spec.json").read_text(encoding="utf-8"))
    if db is not None:
        from dss.spec.validate import synthetic_participation
        from dss.spec.layout import with_synthetic_label
        document = with_synthetic_label(document, synthetic_participation(db, build_id, folder))
    from dss.spec.layout import require_synthetic_label
    require_synthetic_label(document)
    return document


@router.get('/{build_id}/design-pages')
def design_pages(build_id: str, request: Request):
    from dss.spec.publication import design_pages as published_pages
    build, folder = current(request.app.state, build_id)
    spec = read_spec(folder) if (folder / 'spec.json').is_file() else None
    pending = episodic.brief_review(request.app.state.db, build_id)
    return {'version': build['current_version'], 'spec_version': spec.spec_version if spec else None,
            'pages': published_pages(spec, folder) if spec else [],
            'review': pending['record']['review'] if pending else None}


class ReviewEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_id: str
    revision: int = Field(strict=True, ge=1)
    brief: dict


class ReviewApprove(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_id: str
    revision: int = Field(strict=True, ge=1)
    sha256: str


class ReviewCancel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_id: str


async def review_body(request, schema):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 256 * 1024:
            raise RunError('invalid_request', 'Brief review request exceeds 256 KiB', 413)
    try:
        body = schema.model_validate_json(data)
        json.dumps(body.model_dump(), allow_nan=False)
        return body
    except (ValidationError, ValueError):
        raise RunError('invalid_request', 'Invalid brief review request', 422) from None


def review_row(state, build_id, review_id, *, pending=True):
    require_build(state.db, build_id)
    row = episodic.brief_review(state.db, build_id, review_id)
    if row is None or (pending and row['state'] != 'pending'):
        raise RunError('review_not_found', 'Brief review not found', 404)
    return row


def review_conflict(review):
    return RunError('brief_review_conflict', 'The brief review changed; reload it', 409,
                    {'revision': review['revision']})


def require_fresh_review(db, config, build_id, record):
    from pathlib import Path
    from dss.spec.publication import review_fingerprint
    from dss.spec.requirements import digest
    try:
        state = {k: v for k, v in record['state'].items() if k != 'approved'}
        fresh = (review_fingerprint(db, config, build_id, Path(record['folder'])) == record['fingerprint']
                 and digest(state) == record['state_digest'])
    except (OSError, ValueError, KeyError):
        fresh = False
    if not fresh:
        raise RunError('brief_review_stale', 'Inputs changed; cancel this review and generate again', 409)


async def edited_brief(state, config, build_id, record, value):
    """Keep an invalid edit inspectable, with safe JSON-pointer diagnostics and its own hash."""
    from pathlib import Path
    from hashlib import sha256
    from dss.harness.nodes import designer, reference_brief as rb
    from dss.harness import stages
    from dss.harness.context import fit_request
    from dss.harness.tracing import Trace
    spec = DashboardSpec.model_validate(record['state']['spec'])
    page = spec.pages[record['review']['page'] - 1]
    raw = rb.canonical(value)
    secrets = tuple(getattr(config, k).get_secret_value() for k in ('google_api_key', 'access_code', 'agent_token'))
    if any(s and s in raw.decode('utf-8') for s in secrets):
        raise RunError('invalid_request', 'Briefs must not contain credentials', 422)
    valid, errors = rb.validated(raw.decode('utf-8'), False, page.index, [c.id for c in page.components])
    def issue_path(error):
        parts = error['path'].removeprefix('answer').lstrip('.').split('.')
        if parts[:1] == ['slots'] and len(parts) == 2 and not parts[1].isdigit():
            # Semantic id diagnostics point into the edited slot array, or its missing set.
            slots = value.get('slots', [])
            index = next((n for n, s in enumerate(slots) if isinstance(s, dict) and s.get('id') == parts[1]), None)
            parts = ['slots', str(index), 'id'] if index is not None else ['slots']
        return '/' + '/'.join(p.replace('~', '~0').replace('/', '~1') for p in parts) if parts != [''] else ''
    issues = [{'path': issue_path(e), 'message': e['message']} for e in errors]
    # Markdown includes only editable text; ids, types and labels come from the candidate.
    labels = {c.id: c for c in page.components}
    text = f"# Page {page.index} brief\n\n## Overall\n\n{str(value.get('overall', '')).strip()}\n"
    for slot in value.get('slots', []) if isinstance(value.get('slots'), list) else []:
        if isinstance(slot, dict) and isinstance(slot.get('id'), str) and slot['id'] in labels:
            c = labels[slot['id']]
            text += f"\n## {c.id} ({c.type}: {c.label})\n\n{str(slot.get('treatment', '')).strip()}\n"
    old = record['review']['brief']
    edited = {**old, 'origin': 'edited', 'brief': value, 'markdown': text, 'sha256': sha256(raw).hexdigest()}
    if valid is not None:
        inputs = record['state']['html_inputs']
        ref = rb.reference(Path(record['folder']))
        node = 'reference_html' if ref else 'designer'
        trace = Trace(state.db, new_id('r'), build_id, record['review']['action'])
        with stages.Execution(config, trace, available=state.harness.models.available).activate():
            model = state.harness.models.llm_for(node)
            memory, request = designer.html_request(model, spec, page,
                first=designer.Designed(**inputs['first']) if inputs['first'] else None,
                revision=inputs['revision'], reference=(ref, inputs['approved'], valid))
            try:
                await fit_request(memory, request, model, {})
            except RunError as exc:
                if exc.code != 'stage_input_over_limit':
                    raise
                issues.append({'path': '', 'message': f"The HTML request would need {exc.detail['tokens']:,} input tokens; "
                               f"the limit is {exc.detail['budget']:,}."})
    return edited, issues


@router.put('/{build_id}/briefs/review')
async def put_brief_review(build_id: str, request: Request):
    from dss.spec.publication import build_lock
    body = await review_body(request, ReviewEdit)
    state = request.app.state
    async with build_lock(state.db, build_id):
        row = review_row(state, build_id, body.review_id)
        record, review = row['record'], row['record']['review']
        if body.revision != review['revision']:
            raise review_conflict(review)
        if build_id in state.harness.active_builds:
            raise RunError('wrong_stage', 'An action is already running for this build', 409)
        require_fresh_review(state.db, state.settings.get(), build_id, record)
        config = state.settings.get()
    # Remote counting must not block reads or cancellation. The CAS below rejects a competing
    # edit/approve/cancel; the freshness check also catches a candidate removed during counting.
    edited, issues = await edited_brief(state, config, build_id, record, body.brief)
    async with build_lock(state.db, build_id):
        latest = review_row(state, build_id, body.review_id)
        if latest['record_json'] != row['record_json']:
            raise review_conflict(latest['record']['review'])
        require_fresh_review(state.db, config, build_id, record)
        review.update(brief=edited, issues=issues, revision=review['revision'] + 1)
        episodic.update_brief_review(state.db, row, record)
        return review


@router.post('/{build_id}/briefs/review/approve', status_code=202)
async def approve_brief_review(build_id: str, request: Request):
    from copy import deepcopy
    from dss.spec.publication import build_lock
    body = await review_body(request, ReviewApprove)
    state = request.app.state
    async with build_lock(state.db, build_id):
        row = review_row(state, build_id, body.review_id, pending=False)
        record, review = row['record'], row['record']['review']
        if body.revision != review['revision'] or body.sha256 != review['brief']['sha256']:
            raise review_conflict(review)
        if row['state'] == 'approved':
            return {'run_id': row['run_id']}
        if row['state'] != 'pending':
            raise RunError('review_not_found', 'Brief review not found', 404)
        config = state.settings.get()
        try:
            require_fresh_review(state.db, config, build_id, record)
        except RunError:
            review['stale'] = True
            episodic.update_brief_review(state.db, row, record)
            raise
        if review['issues']:
            raise RunError('artifact_invalid', 'Fix the brief review issues before approving', 409,
                           {'issues': review['issues']})
        if build_id in state.harness.active_builds:
            raise RunError('wrong_stage', 'An action is already running for this build', 409)
        run_id = new_id('r')
        episodic.update_brief_review(state.db, row, record, state='approved', run_id=run_id)
        continuation = deepcopy(record)
        continuation['state']['approved'] = review['brief']
        state.harness.active_builds.add(build_id)
        async def background():
            try:
                await state.harness.run(review['action'], build_id,
                    {'config': config, 'factory': state.bigquery_factory, '_brief_resume': continuation},
                    run_id=run_id, reserved=True)
            except RunError:
                pass
        task = asyncio.create_task(background())
        state.engine_tasks.add(task)
        task.add_done_callback(state.engine_tasks.discard)
        return {'run_id': run_id}


@router.post('/{build_id}/briefs/review/cancel')
async def cancel_brief_review(build_id: str, request: Request):
    from pathlib import Path
    import shutil
    from dss.api.builds import build_response
    from dss.spec.publication import build_lock, Candidate, finish
    body = await review_body(request, ReviewCancel)
    state = request.app.state
    async with build_lock(state.db, build_id):
        require_build(state.db, build_id)
        row = episodic.brief_review(state.db, build_id, body.review_id)
        cancelled = row is not None and row['state'] == 'pending'
        if cancelled:
            if build_id in state.harness.active_builds:
                raise RunError('wrong_stage', 'An action is already running for this build', 409)
            episodic.update_brief_review(state.db, row, row['record'], state='cancelled')
            state.harness.active_builds.add(build_id)
    if cancelled:
        try:
            record = row['record']
            if record['review']['action'] == 'prototype':
                await finish(Candidate(state.db, state.settings.get(), record['owner']), state.bigquery_factory)
            else:
                folder = Path(record['folder'])
                expected = state.settings.get().data_dir / '.brief-reviews' / record['owner']
                if folder.resolve() != expected.resolve():
                    raise RunError('brief_review_stale', 'Review candidate identity changed', 409)
                if folder.exists():
                    shutil.rmtree(folder)
        finally:
            state.harness.active_builds.discard(build_id)
    return build_response(state.db, state.settings.get(), build_id)


@router.get("/{build_id}/prototype", response_class=HTMLResponse)
def prototype(build_id: str, request: Request, layer: Literal["all", "decoration"] | None = Query(default=None)):
    _, folder = current(request.app.state, build_id)
    dashboard = read_spec(folder, db=request.app.state.db, build_id=build_id)
    cache_path = folder / 'aggregate-cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    data = {}
    for page in dashboard.pages:
        for item in page.components:
            sql = aggregate_sql(dashboard, item)
            if sql:
                data[item.id] = cache.get(sha256(sql.encode()).hexdigest(), [])
    return render(dashboard, layer=layer, data=data, folder=folder)


@router.get("/{build_id}/spec")
def spec(build_id: str, request: Request):
    _, folder = current(request.app.state, build_id)
    return read_spec(folder, db=request.app.state.db, build_id=build_id).model_dump()


@router.post('/{build_id}/comments', status_code=202)
async def comments(build_id: str, body: Comments, request: Request):
    state = request.app.state
    build, folder = mutation_current(state, build_id)
    if build['stage'] != 'prototype' or build_id in state.harness.active_builds:
        raise RunError('wrong_stage', 'Comments require an idle prototype', 409, {'stage':build['stage']})
    document = read_spec(folder, db=state.db, build_id=build_id)
    ids = {item.id for page in document.pages for item in page.components + page.decorations}
    values = [comment.model_dump() for comment in body.comments]
    if any(comment['component_id'] not in ids for comment in values):
        raise RunError('invalid_request', 'Comment item does not exist in the current spec', 422)
    config = state.settings.get()
    text = check_reply(json.dumps(values), (config.google_api_key.get_secret_value(),))
    run_id = new_id('r')
    # The batch ledger owns intent; this message is chat history, not another source.
    episodic.save(state.db, build_id, 'user', text, 'comment_batch')
    state.harness.active_builds.add(build_id)
    async def background():
        try:
            await state.harness.run('revise', build_id,
                {'comments':values, 'config':config, 'factory':state.bigquery_factory},
                run_id=run_id, reserved=True)
        except RunError:
            pass
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {'run_id':run_id}


@router.post('/{build_id}/audit', status_code=202)
async def audit(build_id: str, request: Request):
    state = request.app.state
    build, folder = mutation_current(state, build_id)
    if build['stage'] != 'prototype' or build_id in state.harness.active_builds:
        raise RunError('wrong_stage', 'A UX audit requires an idle prototype', 409, {'stage':build['stage']})
    read_spec(folder)
    config = state.settings.get()
    run_id = new_id('r')
    state.harness.active_builds.add(build_id)
    async def background():
        try:
            await state.harness.run('ux_audit', build_id, {'config':config}, run_id=run_id, reserved=True)
        except RunError:
            pass
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {'run_id':run_id}
