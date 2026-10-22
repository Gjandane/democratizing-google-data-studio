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


class RevisionModel(FakeLLM):
    """Keep patch fakes focused while supplying a separate intent extraction response."""
    delegate: FakeLLM
    extract_calls: int = 0

    async def count_request_tokens(self, llm_request):
        counter = getattr(self.delegate, 'count_request_tokens', None)
        from dss.harness.context import request_estimate
        return await counter(llm_request) if counter else request_estimate(llm_request)

    async def generate_content_async(self, llm_request, stream=False):
        if llm_request.config.response_json_schema.get('title') != 'Extraction':
            async for result in self.delegate.generate_content_async(llm_request, stream):
                yield result
            return
        self.extract_calls += 1
        text = str(llm_request.config.system_instruction)
        sources = json.loads(text.split('New sources (untrusted; preserve IDs):', 1)[1].strip())
        requirements = []
        for s in sources:
            capability = ('chart.gauge' if 'gauge' in s['text'] else
                          'layout.background_image' if s.get('component_id') == 'p1_title' else 'chart.scorecard')
            properties = ([{'path': 'style.font_size', 'value': 40}] if s.get('component_id') == 'p1_title' and 'bigger' in s['text'] else
                          [{'path': 'text', 'value': 'Sales overview'}] if s.get('component_id') == 'p1_title' else
                          [{'path': 'label', 'value': s['text'].removeprefix('call it ')}] if s['text'].startswith('call it ') else [])
            requirements.append({'source_id': s['id'], 'text': s['text'], 'needs': [{'capability': capability}], 'properties': properties})
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=json.dumps({'requirements': requirements}))]))


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


@pytest.mark.parametrize('colors', [[], ['blue'], ['#123456'] * 21, [123456]])
def test_chart_palette_rejects_invalid_and_mutated_values(colors):
    from pydantic import ValidationError
    from dss.recipe.compiler import compile_recipe
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    raw = spec.pages[0].components[0].model_dump()
    raw['colors'] = colors
    with pytest.raises(ValidationError):
        type(spec.pages[0].components[0]).model_validate(raw)
    spec.pages[0].components[0].colors = colors
    with pytest.raises(ValidationError):
        compile_recipe(spec, 1)


def test_chart_palette_uses_registry_and_preserves_legacy_fallback():
    from dss.spec.capabilities import Checker, load_registry
    from dss.render.prototype import chart_option
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    component = spec.pages[0].components[1]  # 19.4: the bar; a scorecard with colors is unsupported_app
    checker = Checker(load_registry())
    assert chart_option(component, [], spec.theme, 500)['color'] == spec.theme.palette
    spec.theme.palette = []
    assert chart_option(component, [], spec.theme, 500)['color'] == [spec.theme.accent]
    component.colors = ['#172554']
    assert not checker.component(component)
    assert chart_option(component, [], spec.theme, 500)['color'] == ['#172554']
    component.type = 'text'
    assert checker.component(component)


def test_scorecard_palette_colors_the_rendered_value():
    from dss.render.prototype import render
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    component = spec.pages[0].components[0]
    data = {component.id: [{'m0': 120}]}
    assert '<div class="value">120.00</div>' in render(spec, data=data)
    component.colors = ['#172554']
    assert '<div class="value" style="color:#172554">120.00</div>' in render(spec, data=data)


@pytest.mark.parametrize('chart_type', ['table', 'pivot_table'])
@pytest.mark.parametrize('accent,text_color', [('#172554', '#FFFFFF'), ('#FFFFCC', '#000000')])
def test_table_palette_colors_header_with_contrasting_text(chart_type, accent, text_color):
    from dss.render.prototype import chart_option
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    component = spec.pages[0].components[0]
    component.type = chart_type
    component.dimensions = ['region', 'category']
    rows = [{'region': 'APAC', 'category': 'Hardware', 'm0': 120}]
    legacy = chart_option(component, rows, spec.theme, 500)['graphic']
    assert all(g['style']['fill'] == spec.theme.text for g in legacy)
    component.colors = [accent]
    graphics = chart_option(component, rows, spec.theme, 500)['graphic']
    assert graphics[0]['type'] == 'rect' and graphics[0]['style']['fill'] == accent
    assert graphics[0]['shape']['height'] == 25
    texts = [g for g in graphics if g['type'] == 'text']
    assert all(g['style']['fill'] == text_color for g in texts if g['style']['fontWeight'] == 'bold')
    assert all(g['style']['fill'] == spec.theme.text for g in texts if g['style']['fontWeight'] == 'normal')


@pytest.mark.parametrize('location', ['APAC', '{"type":"Point","coordinates":[120,14]}'])
def test_geo_palette_colors_both_map_and_point_visual_ranges(location):
    from dss.render.prototype import chart_option
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    component = spec.pages[0].components[0]
    component.type = 'geo_map'
    component.dimensions = ['location']
    rows = [{'location': location, 'm0': 120}]
    assert chart_option(component, rows, spec.theme, 500)['visualMap']['inRange']['color'] == [spec.theme.surface, spec.theme.accent]
    component.colors = ['#172554']
    assert chart_option(component, rows, spec.theme, 500)['visualMap']['inRange']['color'] == [spec.theme.surface, '#172554']


class FakeBigQuery:
    def __init__(self):
        self.queries = []
    def aggregate(self, sql):
        self.queries.append(sql)
        return [{'region':'APAC', 'm0':224.48}]


def seed_revision(app, build_id, monkeypatch):
    """A prototype ready for a real revision; shared with the agent-mode run tests."""
    config = app.state.settings.get()
    folder = config.data_dir / 'builds' / build_id / 'v1'
    (folder / 'docs').mkdir(parents=True, exist_ok=True)
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    spec.build_id = build_id
    (folder / 'spec.json').write_text(spec.model_dump_json(),encoding='utf-8')
    (folder / 'prototype.html').write_text('previous prototype')
    (folder / 'background_p1.png').write_bytes(b'previous background')
    write_doc(folder/'docs/decisions.md', {'type':'Design Decisions'}, '# Decisions\n')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?",(build_id,))
        conn.execute("INSERT OR REPLACE INTO versions(build_id,n,status,spec_version,created_at) VALUES(?,1,'draft',1,?)",(build_id,now()))
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


@pytest.fixture
def setup(client, app, build_id, monkeypatch):
    return seed_revision(app, build_id, monkeypatch)


def response(*patches):
    return json.dumps({'changes':[{'comment_index':i, 'patch':patch} for i,patch in enumerate(patches)]})


def op(path, value, kind='replace'):
    return {'op':kind,'path':path,'value':value}


async def run(setup, raw, comments=None, fake=None):
    app, build_id, folder, original, service, _ = setup
    fake = fake or FakeLLM(response=raw)
    result = await app.state.harness.run('revise', build_id,
        {'config':app.state.settings.get(),'factory':lambda config:service,
         'comments':comments or [{'component_id':'p1_revenue','text':'make this bigger'}]}, llm=RevisionModel(delegate=fake))
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
    fake = FakeLLM(response=raw)
    with pytest.raises(RunError) as error:
        await run(setup,raw,[{'component_id':'p1_revenue','text':'make it a gauge'}], fake=fake)
    assert error.value.code == 'feasibility_blocked' and fake.calls == 0
    assert DashboardSpec.model_validate_json((folder/'spec.json').read_text()) == original and not captured
    assert 'gauge' in messages(app.state.db,bid)[-1]['text'].lower()


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
    monkeypatch.setattr(app.state.models,'llm_for',lambda node:RevisionModel(delegate=fake))
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


# Label and geometry change on the commented scorecard, moving its neighbour clear.
REVISED = [op('/pages/0/components/0/label','Net revenue'),op('/pages/0/components/0/grid/w',8),
           op('/pages/0/components/1/grid/row',26)]


def revise_through_api(client, app, bid, patch=REVISED):
    """Publish a real revision through the comments API and wait for it to finish."""
    import time
    fake = FakeLLM(response=response(patch))
    app.state.models.llm_for = lambda node: RevisionModel(delegate=fake)
    accepted = client.post(f'/api/builds/{bid}/comments',json={'comments':[{'component_id':'p1_revenue','text':'Net, and wider'}]})
    assert accepted.status_code == 202, accepted.text
    for _ in range(500):
        if not app.state.engine_tasks: break
        time.sleep(.01)
    assert not app.state.engine_tasks
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT status FROM traces WHERE run_id=?',(accepted.json()['run_id'],)).fetchone()[0] == 'ok'
    revised = DashboardSpec.model_validate_json((app.state.settings.get().data_dir/'builds'/bid/'v1'/'spec.json').read_text())
    assert revised.spec_version == 2 and revised.pages[0].components[0].label == 'Net revenue'
    return revised


def test_run_executes_revised_spec_not_compiled_recipe(setup, client, monkeypatch):
    import sys
    from dss.recipe.compiler import compile_recipe
    from test_execute import engine_inputs
    from test_thin_slice import ROOT, wait_done
    app,bid,folder,original,_,_ = setup
    monkeypatch.setenv('DSS_ENGINE_CMD', f'"{sys.executable}" "{ROOT / "tests/fake_engine.py"}"')
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    stale = (folder/'recipe.jsonl').read_text(encoding='utf-8')
    revised = revise_through_api(client, app, bid)
    assert (folder/'recipe.jsonl').read_text(encoding='utf-8') == stale  # revision never recompiles
    seen = engine_inputs(monkeypatch)
    assert client.post(f'/api/builds/{bid}/run').status_code == 202
    assert wait_done(client, bid)['stage'] == 'done'
    expected = compile_recipe(revised, 1)
    assert seen == [expected] and expected != stale
    chart = json.loads(expected.split('\n')[5])  # after open_report, rename_page, canvas, background
    assert chart['component_id'] == 'p1_revenue' and chart['title'] == 'Net revenue' and chart['w'] > 568


async def test_revise_counts_the_whole_request(setup):
    from test_context import assert_counted, counting
    app = setup[0]
    _, fake, _ = await run(setup, '', fake=counting(FakeLLM)(response=response([op('/pages/0/components/0/label', 'Revenue total')])))
    with app.state.db.connect() as conn:
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE node='revise'").fetchone()[0])
    assert_counted(next(s for s in spans if s['node'] == 'revise'), fake)
    assert fake.calls == 1


class CommentFlow(FakeLLM):
    needs_by_text: dict[str, list[dict]]
    extractions: int = 0
    revisions: int = 0
    invalid_extraction: bool = False
    properties_by_text: dict[str, list[dict]] = {}

    async def generate_content_async(self, request, stream=False):
        if request.config.response_json_schema.get('title') == 'Extraction':
            self.extractions += 1
            sources = json.loads(str(request.config.system_instruction).split('New sources (untrusted; preserve IDs):', 1)[1].strip())
            raw = 'invalid' if self.invalid_extraction else json.dumps({'requirements': [
                {'source_id': s['id'], 'text': s['text'], 'needs': self.needs_by_text[s['text']],
                 'properties': self.properties_by_text.get(s['text'], [])} for s in sources]})
        else:
            self.revisions += 1
            assert 'Active requirement ledger and explicit decisions' in str(request.config.system_instruction)
            raw = self.response
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=raw)]))


def post_batch(client, app, bid, comments):
    from test_audit_style import drain
    accepted = client.post(f'/api/builds/{bid}/comments', json={'comments': comments})
    assert accepted.status_code == 202, accepted.text
    client.portal.call(drain, app)
    return client.get(f'/api/builds/{bid}/feasibility').json()


def reapply_batch(client, app, bid, assessment):
    from test_audit_style import drain
    result = client.post(f'/api/builds/{bid}/feasibility/reapply', json={
        'assessment_id': assessment['id'], 'batch_id': assessment['pending_comments']['id']})
    assert result.status_code == 202, result.text
    client.portal.call(drain, app)
    return client.get(f'/api/builds/{bid}/feasibility').json()


def published(folder):
    return {name: (folder/name).read_bytes() for name in ('spec.json', 'prototype.html', 'background_p1.png', 'recipe.jsonl')}


def test_mixed_comment_batch_blocks_before_patching_and_abandons_only_batch(setup, client, monkeypatch):
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    (folder/'recipe.jsonl').write_bytes(b'previous recipe')
    before = published(folder)
    comments = [{'component_id': 'p1_revenue', 'text': 'Title: New revenue'},
                {'component_id': 'p1_by_region', 'text': 'Animate GPS points'}]
    # Use the real second target ID from the fixture.
    comments[1]['component_id'] = setup[3].pages[0].components[1].id
    fake = CommentFlow(needs_by_text={'Title: New revenue': [{'capability': 'argument.title'}],
        'Animate GPS points': [{'capability': 'animation.temporal_playback'}]}, response=response([]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assessment = post_batch(client, app, bid, comments)
    assert assessment['state'] == 'blocked' and assessment['pending_comments']['comments'] == comments
    assert fake.extractions == 1 and fake.revisions == 0 and published(folder) == before
    assert client_stage(app, bid) == 'prototype'
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT * FROM traces').fetchall()
        assert len(traces) == 1 and traces[0]['error'] == 'feasibility_blocked'
        assert conn.execute('SELECT spec_version FROM versions WHERE build_id=?', (bid,)).fetchone()[0] == 1
    assert 'Animate GPS points' in messages(app.state.db, bid)[-1]['text']
    removed = client.delete(f'/api/builds/{bid}/feasibility/pending-comments', params={'assessment_id': assessment['id']})
    assert removed.status_code == 200 and removed.json()['state'] == 'ready' and not removed.json()['prototype_stale']
    assert not req.load(folder).requirements and published(folder) == before
    # Chat history must never resurrect an abandoned batch.
    client.post(f'/api/builds/{bid}/feasibility/check')
    from test_audit_style import drain
    client.portal.call(drain, app)
    assert fake.extractions == 1 and not req.load(folder).requirements


def test_supported_batch_one_trace_and_atomic_proof(setup, client, monkeypatch):
    from dss.spec import requirements as req
    from dss.spec.capabilities import Checker, load_registry
    app, bid, folder, *_ = setup
    fake = CommentFlow(needs_by_text={'Compact numbers': [{'capability': 'option.scorecard.compact_numbers', 'value': True}]},
                       response=response([op('/pages/0/components/0/options/compact_numbers', True, 'add')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assessment = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Compact numbers'}])
    assert fake.extractions == fake.revisions == 1
    assert assessment['state'] == 'ready' and not assessment['prototype_stale'] and assessment['pending_comments'] is None
    ledger = req.load(folder)
    assert not req.coverage_errors(req.inputs(app.state.db, bid, folder), ledger, Checker(load_registry()))
    assert ledger.requirements[0].component_ids == ['p1_revenue']
    assert ledger.verification[ledger.requirements[0].id][-1] == {'fulfilled_by': ['p1_revenue']}
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces').fetchone()[0] == 1


def test_component_dark_blue_accent_changes_only_its_recipe_style(setup, client, monkeypatch):
    # 19.2: the bar, not the scorecard: scorecards have no series swatch and get no set_style.
    from dss.recipe.compiler import compile_recipe
    app, bid, folder, original, service, *_ = setup
    comment = 'Use a dark blue accent for this component; preserve its position and data.'
    fake = CommentFlow(needs_by_text={comment: [{'capability': 'style.colors', 'value': ['#172554']}]},
        response=response([op('/pages/0/components/1/colors', ['#172554'], 'add')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    before = [json.loads(line) for line in compile_recipe(original, 1).splitlines()]
    assessment = post_batch(client, app, bid, [{'component_id': 'p1_regions', 'text': comment}])
    assert assessment['state'] == 'ready' and assessment['pending_comments'] is None, assessment
    revised = DashboardSpec.model_validate_json((folder/'spec.json').read_text())
    expected = original.model_dump()
    expected['spec_version'] = revised.spec_version
    expected['pages'][0]['components'][1]['colors'] = ['#172554']
    assert revised.model_dump() == expected
    after = [json.loads(line) for line in compile_recipe(revised, 1).splitlines()]
    changed = [(old, new) for old, new in zip(before, after) if old != new]
    assert len(changed) == 1
    assert changed[0][0]['op'] == changed[0][1]['op'] == 'set_style'
    assert changed[0][1]['component_id'] == 'p1_regions'
    assert changed[0][1]['style'] == {'colors': ['#172554']}
    assert fake.extractions == fake.revisions == 1 and not service.queries


def test_scorecard_color_comment_fails_fast(setup, client, monkeypatch):
    """19.4: scorecards get no set_style, so a color comment on one is unsupported_app, not merely pending."""
    app, bid, folder, *_ = setup
    comment = 'Use a dark blue accent for this component; preserve its position and data.'
    fake = CommentFlow(needs_by_text={comment: [{'capability': 'style.colors', 'value': ['#172554']}]},
        response=response([op('/pages/0/components/0/colors', ['#172554'], 'add')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    original = (folder/'spec.json').read_bytes()
    assessment = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': comment}])
    assert (folder/'spec.json').read_bytes() == original
    assert assessment['state'] == 'blocked' and fake.revisions == 0, assessment
    assert assessment['pending_comments']['comments'] == [{'component_id': 'p1_revenue', 'text': comment}]
    assert any(i['status'] == 'unsupported_app' and 'scorecards' in i['reason'].lower() and 'colors' in i['reason'].lower() for i in assessment['issues']), assessment


@pytest.mark.parametrize('count', [1, 2])
def test_scoped_overrides_preserve_global_palette_when_every_chart_changes(setup, client, monkeypatch, count):
    from dss.memory import episodic
    app, bid, folder, original, *_ = setup
    original.theme.palette = ['#1E40AF']
    original.pages[0].components = original.pages[0].components[:count]
    # 19.2: a scorecard gets no set_style (no series swatch), so a color comment on it can't
    # verify against the recipe; every chart here is one with swatches.
    for c in original.pages[0].components:
        if c.type == 'scorecard':
            c.type, c.options, c.dimensions, c.grid.h = 'bar', {}, ['region'], 8  # bar min h
    (folder / 'spec.json').write_text(original.model_dump_json(), encoding='utf-8')
    theme = 'Use a clean blue theme'
    episodic.save(app.state.db, bid, 'user', theme)
    comment = 'Use a dark blue accent for this component; preserve its position and data.'
    fake = CommentFlow(needs_by_text={theme: [{'capability': 'style.colors', 'value': ['#1E40AF']}],
        comment: [{'capability': 'style.colors', 'value': ['#172554']}]},
        response=response(*[[op(f'/pages/0/components/{i}/colors', ['#172554'], 'add')] for i in range(count)]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assessment = post_batch(client, app, bid, [{'component_id': c.id, 'text': comment} for c in original.pages[0].components])
    assert assessment['state'] == 'ready' and assessment['pending_comments'] is None, assessment
    revised = json.loads((folder / 'spec.json').read_text())
    assert revised['theme']['palette'] == ['#1E40AF']
    assert all(c['colors'] == ['#172554'] for c in revised['pages'][0]['components'])


@pytest.mark.parametrize('already_satisfied', [False, True])
def test_empty_revision_clears_batch_only_if_intent_is_proven(setup, client, monkeypatch, already_satisfied):
    app, bid, folder, spec, *_ = setup
    if already_satisfied:
        spec.pages[0].components[0].options['compact_numbers'] = True
        (folder/'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    fake = CommentFlow(needs_by_text={'Compact numbers': [{'capability': 'option.scorecard.compact_numbers', 'value': True}]}, response=response([]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    original = (folder/'spec.json').read_bytes()
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Compact numbers'}])
    assert fake.revisions == (1 if already_satisfied else 2)  # Still exactly one repair.
    assert (a['pending_comments'] is None) == already_satisfied
    assert a['prototype_stale'] != already_satisfied
    assert (folder/'spec.json').read_bytes() == original


def test_choose_reload_reapply_preserves_authorization_and_changed_text_invalidates(setup, client, monkeypatch):
    from dss.spec import requirements as req
    app, bid, folder, spec, *_ = setup
    # A connected date makes the registry's explicit time-series offer possible.
    from dss.spec.models import DataField
    spec.datasource.fields.append(DataField(name='observed_at', type='DATE', label='Observed at', role='dimension'))
    (folder/'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    (folder/'recipe.jsonl').write_bytes(b'previous recipe')
    before = published(folder)
    fake = CommentFlow(needs_by_text={text: [{'capability': 'animation.temporal_playback'}]
        for text in ('Animate GPS points', 'Animate differently')}, response=response([
            op('/pages/0/components/0/type', 'time_series'),
            op('/pages/0/components/0/date_dimension', 'observed_at'),
            op('/pages/0/components/0/grid/h', 10)]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Animate GPS points'}])
    issue = a['issues'][0]
    chosen = client.post(f'/api/builds/{bid}/feasibility/decisions', json={'assessment_id': a['id'], 'decisions': [{
        'issue_id': issue['id'], 'action': 'accept_alternative', 'alternative_id': issue['alternatives'][0]['id']}]})
    assert chosen.status_code == 200 and published(folder) == before
    b = client.get(f'/api/builds/{bid}/feasibility').json()
    assert b['state'] == 'ready' and b['prototype_stale'] and fake.revisions == 0
    c = reapply_batch(client, app, bid, b)
    assert c['state'] == 'ready' and c['pending_comments'] is None and not c['prototype_stale'], c
    assert fake.extractions == 1 and fake.revisions == 1
    assert req.load(folder).decisions[0]['applied']
    assert json.loads((folder/'spec.json').read_text())['spec_version'] == 2
    assert (folder/'recipe.jsonl').read_bytes() == before['recipe.jsonl']
    d = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Animate differently'}])
    assert d['state'] == 'blocked' and any(i['requirement'] == 'Animate differently' and i['resolution'] == 'unresolved' for i in d['issues'])
    assert fake.extractions == 2 and fake.revisions == 1


def test_extraction_failure_preserves_prior_batch_and_artifacts(setup, client, monkeypatch):
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    (folder/'recipe.jsonl').write_bytes(b'previous recipe')
    fake = CommentFlow(needs_by_text={'Animate': [{'capability': 'animation.temporal_playback'}]})
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Animate'}])
    before, ledger = published(folder), (folder/'requirements.json').read_bytes()
    fake.invalid_extraction = True
    post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Changed'}])
    assert published(folder) == before and (folder/'requirements.json').read_bytes() == ledger
    assert req.load(folder).pending_comments.comments[0].text == 'Animate'


@pytest.mark.parametrize('refused', [False, True])
def test_reviser_cannot_partially_apply_an_assessed_batch(setup, client, monkeypatch, refused):
    app, bid, folder, *_ = setup
    (folder/'recipe.jsonl').write_bytes(b'previous recipe')
    before = published(folder)
    raw = json.loads(response([op('/pages/0/components/0/label', 'New')],
                             [op('/pages/0/components/1/type', 'gauge')]))
    if refused:
        raw['changes'][1] = {'comment_index': 1, 'patch': [], 'unsupported_type': 'gauge'}
    fake = CommentFlow(needs_by_text={'New name': [{'capability': 'argument.title'}],
        'Keep the bar': [{'capability': 'chart.bar'}]}, response=json.dumps(raw))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'New name'},
                                    {'component_id': 'p1_regions', 'text': 'Keep the bar'}])
    assert fake.revisions == 2 and a['pending_comments'] and published(folder) == before


def test_publication_failure_rolls_back_proof_spec_and_artifacts(setup, client, monkeypatch):
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    (folder/'recipe.jsonl').write_bytes(b'previous recipe')
    before = published(folder)
    real = Path.replace
    def fail(path, target):
        if path.name.startswith('publish-') and Path(target).name == 'requirements.json':
            raise OSError('injected proof publication failure')
        return real(path, target)
    monkeypatch.setattr(Path, 'replace', fail)
    fake = CommentFlow(needs_by_text={'New title': [{'capability': 'argument.title'}]},
                       response=response([op('/pages/0/components/0/label', 'New')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'New title'}])
    assert fake.revisions == 1 and a['pending_comments'] and published(folder) == before
    assert req.load(folder).pending_comments is not None
    assert '"comment":' not in (folder/'docs/decisions.md').read_text()
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT spec_version FROM versions WHERE build_id=?', (bid,)).fetchone()[0] == 1


def test_drop_reapply_noop_retains_independent_staleness(setup, client, monkeypatch):
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    ledger = req.load(folder)
    ledger.prototype_stale = True
    req.save(folder, ledger)
    fake = CommentFlow(needs_by_text={'Animate': [{'capability': 'animation.temporal_playback'}]}, response=response([]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Animate'}])
    result = client.post(f'/api/builds/{bid}/feasibility/decisions', json={'assessment_id': a['id'], 'decisions': [{
        'issue_id': a['issues'][0]['id'], 'action': 'drop', 'alternative_id': None}]})
    assert result.status_code == 200
    original = (folder/'spec.json').read_bytes()
    b = reapply_batch(client, app, bid, result.json())
    assert b['state'] == 'ready' and b['pending_comments'] is None and b['prototype_stale']
    assert fake.extractions == fake.revisions == 1 and (folder/'spec.json').read_bytes() == original


@pytest.mark.parametrize('size', [None, 32, 40])
def test_decoration_revision_proves_requested_property(setup, client, monkeypatch, size):
    app, bid, folder, *_ = setup
    fake = CommentFlow(needs_by_text={'Title size 40': [{'capability': 'layout.background_image'}]},
        properties_by_text={'Title size 40': [{'path': 'style.font_size', 'value': 40}]},
        response=response([] if size is None else [op('/pages/0/decorations/0/style/font_size', size, 'add')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    original = (folder/'spec.json').read_bytes()
    a = post_batch(client, app, bid, [{'component_id': 'p1_title', 'text': 'Title size 40'}])
    assert (a['pending_comments'] is None) == (size == 40)
    if size != 40:
        assert (folder/'spec.json').read_bytes() == original and fake.revisions == 2


def test_later_comment_property_overrides_preserve_provenance_and_abandon_restores(setup, client, monkeypatch):
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    fake = CommentFlow(needs_by_text={s: [{'capability': 'option.scorecard.compact_numbers', 'value': value}]
        for s, value in [('Enable compact', True), ('Disable compact', False)]},
        response=response([op('/pages/0/components/0/options/compact_numbers', True, 'add')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Enable compact'}])
    assert a['pending_comments'] is None
    old_id = req.load(folder).requirements[0].id
    # Failed replacement remains pending; abandon reactivates exactly the old assignment.
    fake.response = response([])
    b = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Disable compact'}])
    assert b['pending_comments'] and req.load(folder).requirements[0].superseded
    result = client.delete(f'/api/builds/{bid}/feasibility/pending-comments', params={'assessment_id': b['id']})
    assert result.status_code == 200 and not req.load(folder).requirements[0].superseded
    fake.response = response([op('/pages/0/components/0/options/compact_numbers', False)])
    c = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Disable compact'}])
    assert c['pending_comments'] is None and c['state'] == 'ready'
    ledger = req.load(folder)
    assert ledger.requirements[0].id == old_id and ledger.requirements[0].source.text == 'Enable compact'
    assert ledger.requirements[0].superseded['need:0'] == ledger.requirements[1].id
    assert json.loads((folder/'spec.json').read_text())['pages'][0]['components'][0]['options']['compact_numbers'] is False
    # A third, failed assignment must not overwrite A -> B when adding B -> C.
    fake.response = response([])
    d = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Enable compact'}])
    assert d['pending_comments']
    result = client.delete(f'/api/builds/{bid}/feasibility/pending-comments', params={'assessment_id': d['id']})
    assert result.status_code == 200
    ledger = req.load(folder)
    assert ledger.requirements[0].superseded['need:0'] == ledger.requirements[1].id
    assert not ledger.requirements[1].superseded
    from dss.spec.capabilities import Checker, load_registry
    assert not req.coverage_errors(req.inputs(app.state.db, bid, folder), ledger, Checker(load_registry()))


def multipage(setup):
    """Replace the seeded prototype with a 3-page spec (band header kit on every page)."""
    from test_render import three_pages
    app, bid, folder, _, service, _ = setup
    spec = three_pages()
    spec.build_id = bid
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    for page in spec.pages[1:]:
        (folder / f'background_p{page.index}.png').write_bytes(b'previous background')
    aggregate_data(spec, service, folder)
    service.queries.clear()
    return spec


@pytest.mark.parametrize('index,key', [(0, 'background_color'), (1, 'color')])
# Live 15.11: an explicit hex in the comment's own words is fulfilled the same way.
@pytest.mark.parametrize('comment,color,as_property', [('Use a dark blue accent for this component', '#172554', False),
                                           ('Use a dark blue accent (#1E3A8A) for this component.', '#1E3A8A', False),
                                           ('Use a dark blue accent (#1E3A8A) for this component.', '#1E3A8A', True)])
def test_decoration_dark_blue_accent_patches_only_that_decoration(setup, client, monkeypatch, index, key, comment, color, as_property):
    """Release 2.2 P1: a color comment on a header decoration is fulfilled, never invalid_request."""
    from dss.spec import requirements as req
    app, bid, folder, _, service, captured = setup
    original = multipage(setup)
    target = original.pages[1].decorations[index]
    assert (target.id, target.kind) == (('p2_header_band', 'band'), ('p2_report_title', 'title'))[index]
    # The extractor may return the color as a need or as a bare color property (live 15.11).
    fake = CommentFlow(needs_by_text={comment: [] if as_property else [{'capability': 'style.colors', 'value': [color]}]},
        properties_by_text={comment: [{'path': 'style.background_color', 'value': color}]} if as_property else {},
        response=response([op(f'/pages/1/decorations/{index}/style/{key}', color)]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assessment = post_batch(client, app, bid, [{'component_id': target.id, 'text': comment}])
    assert assessment['state'] == 'ready' and assessment['pending_comments'] is None, assessment
    assert fake.extractions == fake.revisions == 1
    revised = DashboardSpec.model_validate_json((folder / 'spec.json').read_text())
    expected = original.model_dump()
    expected['spec_version'] = original.spec_version + 1
    expected['pages'][1]['decorations'][index]['style'][key] = color
    assert revised.model_dump() == expected
    row = req.load(folder).requirements[0]
    assert row.component_ids == [target.id] and [p.model_dump() for p in row.properties] == [
        {'path': f'style.{key}', 'value': color}]
    # The decoration is flattened into page 2's re-rendered background only.
    page_two = next(html for html in captured if 'data-page="2"' in html)
    assert color in page_two and all(color not in html for html in captured if html is not page_two)
    assert (folder / 'background_p2.png').read_bytes() == b'new background'
    assert comment in (folder / 'docs/decisions.md').read_text(encoding='utf-8')
    assert not service.queries


def test_decoration_accent_with_wrong_color_is_not_fulfilled(setup, client, monkeypatch):
    app, bid, folder, *_ = setup
    multipage(setup)
    before = (folder / 'spec.json').read_bytes()
    comment = 'Use a dark blue accent for this component'
    fake = CommentFlow(needs_by_text={comment: [{'capability': 'style.colors', 'value': ['#172554']}]},
        response=response([op('/pages/1/decorations/0/style/background_color', '#1E40AF')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assessment = post_batch(client, app, bid, [{'component_id': 'p2_header_band', 'text': comment}])
    assert assessment['pending_comments'] and fake.revisions == 2
    assert (folder / 'spec.json').read_bytes() == before


@pytest.mark.parametrize('extracted', [[], [{'capability': 'unknown.unclassified'}]])
def test_remove_this_chart_deletes_component_and_records_decision(setup, client, monkeypatch, extracted):
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    original = multipage(setup)
    target = original.pages[1].components[4]
    assert target.id == 'p2_bar_4'
    fake = CommentFlow(needs_by_text={'Remove this chart': extracted},
                       response=response([{'op': 'remove', 'path': '/pages/1/components/4'}]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assessment = post_batch(client, app, bid, [{'component_id': target.id, 'text': 'Remove this chart'}])
    assert assessment['state'] == 'ready' and assessment['pending_comments'] is None, assessment
    revised = DashboardSpec.model_validate_json((folder / 'spec.json').read_text())
    expected = original.model_dump()
    expected['spec_version'] = original.spec_version + 1
    del expected['pages'][1]['components'][4]
    assert revised.model_dump() == expected
    assert req.removal(req.load(folder).requirements[0]) == target.id
    decisions = (folder / 'docs/decisions.md').read_text(encoding='utf-8')
    assert 'Remove this chart' in decisions and f'"removed": "{target.id}"' in decisions
    assert f'data-cid="{target.id}"' not in (folder / 'prototype.html').read_text(encoding='utf-8')
    assert ('prototype.updated', {'spec_version': revised.spec_version}) in events(app, bid)


def test_removal_retires_earlier_comment_rows_and_must_actually_remove(setup, client, monkeypatch):
    app, bid, folder, *_ = setup
    multipage(setup)
    fake = CommentFlow(needs_by_text={'Compact numbers': [{'capability': 'option.scorecard.compact_numbers', 'value': True}],
                                      'Remove this chart': []},
                       response=response([op('/pages/1/components/0/options/compact_numbers', True, 'add')]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    assert post_batch(client, app, bid, [{'component_id': 'p2_scorecard_0', 'text': 'Compact numbers'}])['pending_comments'] is None
    # An empty patch does not fulfill a removal: one repair, then the batch stays pending.
    fake.response = response([])
    before = (folder / 'spec.json').read_bytes()
    pending = post_batch(client, app, bid, [{'component_id': 'p2_scorecard_0', 'text': 'Remove this chart'}])
    assert pending['pending_comments'] and (folder / 'spec.json').read_bytes() == before
    client.delete(f'/api/builds/{bid}/feasibility/pending-comments', params={'assessment_id': pending['id']})
    fake.response = response([{'op': 'remove', 'path': '/pages/1/components/0'}])
    done = post_batch(client, app, bid, [{'component_id': 'p2_scorecard_0', 'text': 'Remove this chart'}])
    assert done['state'] == 'ready' and done['pending_comments'] is None, done
    assert 'p2_scorecard_0' not in (folder / 'spec.json').read_text()


@pytest.mark.parametrize('orientation', ['horizontal', 'vertical'])
def test_removal_retires_unscoped_row_only_the_removed_chart_fulfilled(setup, client, monkeypatch, orientation):
    """An unscoped (message) row retires with its only fulfilling chart; one another chart misses still blocks."""
    from dss.memory import episodic
    app, bid, folder, *_ = setup
    spec = multipage(setup)
    spec.pages[1].components[4].options = {'orientation': orientation}
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    request = 'Show a horizontal bar chart'
    episodic.save(app.state.db, bid, 'user', request)
    fake = CommentFlow(needs_by_text={request: [{'capability': 'option.bar.orientation', 'value': 'horizontal'}],
                                      'Remove this chart': []},
                       response=response([{'op': 'remove', 'path': '/pages/1/components/4'}]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    before = (folder / 'spec.json').read_bytes()
    result = post_batch(client, app, bid, [{'component_id': 'p2_bar_4', 'text': 'Remove this chart'}])
    if orientation == 'horizontal':
        assert result['state'] == 'ready' and result['pending_comments'] is None, result
        assert 'p2_bar_4' not in (folder / 'spec.json').read_text()
    else:
        # The row was never fulfilled by the removed chart: removal cannot launder it.
        assert result['pending_comments'] or result['state'] != 'ready'
        assert (folder / 'spec.json').read_bytes() == before


def test_patch_scope_spans_pages_but_not_across_them():
    from test_render import three_pages
    document = three_pages().model_dump()
    renamed = apply_scoped(document, [op('/pages/2/components/0/label', 'Renamed')], 'p3_scorecard_0')
    assert renamed['pages'][2]['components'][0]['label'] == 'Renamed'
    # Page 1's item in the same grid cells is not a collision neighbour of a page 3 item.
    with pytest.raises(PatchError):
        apply_scoped(document, [op('/pages/2/components/0/grid/w', 6), op('/pages/0/components/1/grid/col', 7)], 'p3_scorecard_0')
    with pytest.raises(PatchError):
        apply_scoped(document, [op('/pages/1/components/0/label', 'x')], 'p3_scorecard_0')
    with pytest.raises(PatchError):
        apply_scoped(document, [op('/pages/01/components/0/label', 'x')], 'p2_scorecard_0')
