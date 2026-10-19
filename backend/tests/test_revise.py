import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from dss.db import now
from dss.harness.guardrails import RunError
from dss.harness.nodes.intake import write_doc
from dss.memory.episodic import messages
from dss.render.prototype import aggregate_data
from dss.spec.models import DashboardSpec
from dss.spec.patch import apply_scoped, PatchError
from dss.spec.validate import validate_spec
from fakes import FakeLLM


def test_provider_schema_retains_application_patch_limits():
    from pydantic import ValidationError
    from dss.harness.nodes.revise import Revision, response_schema
    schema = response_schema()
    assert 'maxItems' not in json.dumps(schema)
    assert schema['$defs']['Operation']['properties']['value']['anyOf']
    with pytest.raises(ValidationError):
        Revision.model_validate({'changes':[{'comment_index':0,'patch':[]}]*21})
    with pytest.raises(ValidationError):
        Revision.model_validate({'changes':[{'comment_index':0,'patch':[
            {'op':'replace','path':'/pages/0/components/0/label','value':'x'}]*41}]})


class FakeBigQuery:
    def __init__(self):
        self.queries = []
    def aggregate(self, sql):
        self.queries.append(sql)
        return [{'region':'APAC', 'm0':224.48}]


@pytest.fixture
def setup(client, app, build_id, monkeypatch):
    config = app.state.settings.get()
    folder = config.data_dir / 'builds' / build_id / 'v1'
    (folder / 'docs').mkdir(parents=True)
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    (folder / 'spec.json').write_text(spec.model_dump_json(),encoding='utf-8')
    (folder / 'prototype.html').write_text('previous prototype')
    (folder / 'background_p1.png').write_bytes(b'previous background')
    write_doc(folder/'docs/decisions.md', {'type':'Design Decisions'}, '# Decisions\n')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?",(build_id,))
        conn.execute("INSERT INTO versions(build_id,n,status,spec_version,created_at) VALUES(?,1,'draft',1,?)",(build_id,now()))
    service = FakeBigQuery()
    aggregate_data(spec, service, folder)
    service.queries.clear()
    captured = []
    def capture(html, path, width, height):
        captured.append(html)
        path.write_bytes(b'new background')
    monkeypatch.setattr('dss.render.background.capture', capture)
    app.state.bigquery_factory = lambda config:service
    return app, build_id, folder, spec, service, captured


def response(*patches):
    return json.dumps({'changes':[{'comment_index':i, 'patch':patch} for i,patch in enumerate(patches)]})


def op(path, value, kind='replace'):
    return {'op':kind,'path':path,'value':value}


async def run(setup, raw, comments=None, fake=None):
    app, build_id, folder, original, service, _ = setup
    fake = fake or FakeLLM(response=raw)
    result = await app.state.harness.run('revise', build_id,
        {'config':app.state.settings.get(),'factory':lambda config:service,
         'comments':comments or [{'component_id':'p1_revenue','text':'make this bigger'}]}, llm=fake)
    return result, fake, DashboardSpec.model_validate_json((folder/'spec.json').read_text())


def events(app, build_id):
    with app.state.db.connect() as conn:
        return [(r[0],json.loads(r[1])) for r in conn.execute('SELECT kind,payload_json FROM events WHERE build_id=? ORDER BY rowid',(build_id,))]


async def test_grow_and_move_neighbour(setup):
    app,bid,folder,original,service,_ = setup
    # Move below both the expanded scorecard and the existing source note.
    patch = [op('/pages/0/components/0/grid/w',8),op('/pages/0/components/1/grid/row',26)]
    result,fake,new = await run(setup,response(patch))
    assert new.pages[0].components[0].grid.w == 8
    assert new.pages[0].components[1].grid.row == 26
    assert not validate_spec(new)
    assert new.spec_version == 2 and original.spec_version == 1
    assert not service.queries
    assert ('prototype.updated',{'spec_version':2}) in events(app,bid)
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT spec_version FROM versions WHERE build_id=?',(bid,)).fetchone()[0] == 2
        traces = conn.execute('SELECT * FROM traces').fetchall()
    assert len(traces)==1 and traces[0]['status']=='ok' and fake.calls==1
    assert 'make this bigger' in (folder/'docs/decisions.md').read_text()
    assert len(messages(app.state.db,bid))==1


@pytest.mark.parametrize('patch', [
    [op('/pages/0/components/2/text','unrelated')],
    [op('/pages/0/components/1/label','unrelated')],
    [op('/pages/0/components/1/grid/row',14)],
    [op('/pages/0/components/0/grid/w',8),op('/pages/0/components/1/grid/w',4),op('/pages/0/components/1/grid/col',9)],
    [op('/title','global')], [op('/datasource/table','evil.project.table')],
    [op('/pages/0/components/0/id','p1_changed')],
    [{'op':'copy','from':'/pages/0/components/2/text','path':'/pages/0/components/0/text'}],
    [op('/pages/0/components/00/grid/w',8)],
])
async def test_scope_rejects_and_retains_published(setup, patch):
    app,bid,folder,original,_,_ = setup
    original_bytes = (folder/'spec.json').read_bytes()
    fake = FakeLLM(response=response(patch))
    with pytest.raises(RunError,match='rejected after one repair'):
        await run(setup,'',fake=fake)
    assert fake.calls==2
    assert (folder/'spec.json').read_bytes()==original_bytes
    assert (folder/'prototype.html').read_text()=='previous prototype'
    assert (folder/'background_p1.png').read_bytes()==b'previous background'
    assert not any(k=='prototype.updated' for k,_ in events(app,bid))
    assert client_stage(app,bid)=='prototype'


def client_stage(app,bid):
    with app.state.db.connect() as conn:
        return conn.execute('SELECT stage FROM builds WHERE id=?',(bid,)).fetchone()[0]


async def test_decoration_rebuilds_only_title(setup):
    app,bid,folder,original,_,captured = setup
    _,_,new = await run(setup,response([op('/pages/0/decorations/0/style/font_size',40,'add')]),
        [{'component_id':'p1_title','text':'make the title bigger'}])
    assert new.pages[0].components == original.pages[0].components
    assert new.pages[0].decorations[0].style == {'font_size':40}
    assert 'font-size:40px' in captured[0]
    assert (folder/'background_p1.png').read_bytes()==b'new background'


@pytest.mark.parametrize('as_patch',[False,True])
async def test_refuses_unavailable_type(setup,monkeypatch,as_patch):
    monkeypatch.setenv('DSS_ALLOWED_TYPES','scorecard,bar,text')
    app,bid,folder,original,_,captured=setup
    raw=response([op('/pages/0/components/0/type','gauge')]) if as_patch else json.dumps({'changes':[{'comment_index':0,'patch':[],'unsupported_type':'gauge'}]})
    result,_,new=await run(setup,raw,[{'component_id':'p1_revenue','text':'make it a gauge'}])
    assert new==original and not captured
    assert 'Data Studio offers' in result['reply'] and 'scorecard' in result['reply']
    assert 'gauge' in (folder/'docs/decisions.md').read_text()
    assert messages(app.state.db,bid)[-1]['text']==result['reply']


async def test_conflicts_last_wins_and_records_each_comment(setup):
    app,bid,folder,_,_,_=setup
    result,_,new=await run(setup,response([op('/pages/0/components/0/label','First')],[op('/pages/0/components/0/label','Last')]),
        [{'component_id':'p1_revenue','text':'call it First'},{'component_id':'p1_revenue','text':'call it Last'}])
    assert new.pages[0].components[0].label=='Last' and new.spec_version==2
    assert 'last change' in result['reply']
    text=(folder/'docs/decisions.md').read_text()
    assert text.count('"comment":')==2 and 'call it First' in text and 'call it Last' in text


async def test_empty_patch_keeps_version_and_logs(setup):
    app,bid,folder,original,_,captured=setup
    result,_,new=await run(setup,response([]))
    assert new==original and 'no change needed' in result['reply'].lower()
    assert not captured and not any(k=='prototype.updated' for k,_ in events(app,bid))
    assert (folder/'docs/decisions.md').read_text().count('"comment":')==1


@pytest.mark.parametrize('patch', [
    [{'op':'remove','path':'/pages/0/components/0/text'}],
    [op('/pages/0/components/0/grid/w','6')],
])
async def test_canonical_no_change_keeps_version(setup, patch):
    app,bid,folder,original,_,captured=setup
    result,_,new=await run(setup,response(patch))
    assert new==original and 'no change needed' in result['reply'].lower()
    assert not captured and not any(k=='prototype.updated' for k,_ in events(app,bid))


async def test_one_repair_and_budget(setup):
    from dss.harness.context import revise_context
    app,bid,folder,_,_,_=setup
    class Repair(FakeLLM):
        async def generate_content_async(self,llm_request,stream=False):
            self.calls+=1
            assert len(llm_request.contents)==1
            assert len(str(llm_request.config.system_instruction))<24000
            if self.calls==2:
                assert 'Validation diagnostics' in llm_request.config.system_instruction
            raw=response([op('/pages/0/components/0/grid/w',8)]) if self.calls==1 else response([op('/pages/0/components/0/label','Revenue total')])
            yield LlmResponse(content=types.Content(role='model',parts=[types.Part(text=raw)]))
    _,fake,new=await run(setup,'',fake=Repair())
    assert fake.calls==2 and new.pages[0].components[0].label=='Revenue total'
    with app.state.db.connect() as conn:
        spans=json.loads(conn.execute('SELECT spans_json FROM traces').fetchone()[0])
    assert all(s['input_tokens_estimate']<=6000 for s in spans if s['node'] in ('revise','revise_repair'))


async def test_render_failure_rolls_back(setup,monkeypatch,caplog):
    app,bid,folder,original,_,_=setup
    before={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    def fail(*args):
        raise RuntimeError('test-key private-render-diagnostic')
    monkeypatch.setattr('dss.render.background.capture',fail)
    with pytest.raises(RunError,match='previous prototype retained'):
        await run(setup,response([op('/pages/0/components/0/label','New')]))
    assert all(p.read_bytes()==value for p,value in before.items())
    assert 'private-render-diagnostic' not in caplog.text
    assert not any(k=='prototype.updated' for k,_ in events(app,bid))


async def test_malformed_and_unsafe_outputs(setup,caplog):
    for raw in ('not json', '{"changes":', '{"changes":[{"comment_index":0,"patch":[],"unsupported_type":"test-key"}]}'):
        with pytest.raises(RunError):
            await run(setup,raw)
    assert 'test-key' not in caplog.text


async def test_api_launch_and_busy_guard(setup,client,monkeypatch):
    app,bid,folder,_,_,_=setup
    started,release=asyncio.Event(),asyncio.Event()
    fake=FakeLLM(response=response([]),started=started,release=release)
    monkeypatch.setattr(app.state.models,'llm_for',lambda node:fake)
    # The TestClient runs the request in its own event loop; poll via the portal.
    result=client.post(f'/api/builds/{bid}/comments',json={'comments':[{'component_id':'p1_title','text':'Looks good'}]})
    assert result.status_code==202 and set(result.json())=={'run_id'}
    second=client.post(f'/api/builds/{bid}/comments',json={'comments':[{'component_id':'p1_title','text':'Again'}]})
    assert second.status_code==409
    client.portal.call(release.set)
    for _ in range(300):
        if not app.state.engine_tasks:break
        await asyncio.sleep(.01)
    assert not app.state.engine_tasks
    assert len(messages(app.state.db,bid))==2


@pytest.mark.parametrize('comments',[[],[{'component_id':'p1_missing','text':'x'}],[{'component_id':'p1_title','text':' '}], [{'component_id':'p1_title','text':'x'}]*21])
def test_api_rejects_invalid_comments(setup,client,comments):
    app,bid,*_=setup
    assert client.post(f'/api/builds/{bid}/comments',json={'comments':comments}).status_code==422
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces').fetchone()[0]==0


def test_context_excludes_unrelated_items_and_limits_budget(setup):
    from dss.harness.context import revise_context
    app,bid,folder,spec,_,_=setup
    document=spec.model_dump()
    context=revise_context(document,[{'component_id':'p1_revenue','text':'bigger'}],{'scorecard','bar','text'})
    assert 'p1_note' not in context
    assert context.index('You revise')<context.index('# Revise')<context.index('Target catalog')<context.index('Comments in application order')
    with pytest.raises(RunError,match='budget'):
        revise_context(document,[{'component_id':'p1_revenue','text':'x'*24001}],{'scorecard'})
