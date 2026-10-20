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
from pydantic import BaseModel, ConfigDict, Field
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


def read_spec(folder):
    if not (folder / "spec.json").is_file():
        raise RunError("wrong_stage", "Load a spec before this action", 409)
    return DashboardSpec.model_validate_json((folder / "spec.json").read_text(encoding="utf-8"))


@router.get("/{build_id}/prototype", response_class=HTMLResponse)
def prototype(build_id: str, request: Request, layer: Literal["all", "decoration"] | None = Query(default=None)):
    _, folder = current(request.app.state, build_id)
    dashboard = read_spec(folder)
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
    return read_spec(folder).model_dump()


@router.post('/{build_id}/comments', status_code=202)
async def comments(build_id: str, body: Comments, request: Request):
    state = request.app.state
    build, folder = current(state, build_id)
    if build['stage'] != 'prototype' or build_id in state.harness.active_builds:
        raise RunError('wrong_stage', 'Comments require an idle prototype', 409, {'stage':build['stage']})
    document = read_spec(folder)
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
    build, folder = current(state, build_id)
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
