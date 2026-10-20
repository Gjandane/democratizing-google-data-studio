import json
import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from fakes import FakeLLM
from dss.harness.guardrails import RunError
from dss.harness.nodes.intake import write_doc
from dss.harness.nodes.spec import datasource_fields
from test_plan import seed, PLAN


def response_for(request):
    context = request.config.system_instruction
    expected = json.JSONDecoder().raw_decode(context.split('Required identity and datasource (copy exactly):\n', 1)[1])[0]
    return {**expected, 'title': 'Revenue', 'canvas': {'width':1200,'height':900},
        'pages':[{'index':1,'name':'Overview','height':900,'components':[
            {'id':'p1_revenue','type':'scorecard','label':'Revenue','grid':{'col':1,'row':1,'w':6,'h':4},
             'metrics':[{'field':'revenue','agg':'sum'}], 'question_ref':'q1'}]}]}


class SpecLLM(FakeLLM):
    invalid: int = 0
    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        spec = response_for(llm_request)
        if self.calls <= self.invalid:
            spec['pages'][0]['components'][0]['metrics'][0]['field'] = 'missing'
        if self.calls > 1:
            assert 'Unknown datasource field' in llm_request.config.system_instruction
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=json.dumps(spec))]))


def spec_seed(app, build_id):
    docs = seed(app, build_id)
    for name in ('brief', 'kpis', 'design', 'decisions'):
        write_doc(docs / (name+'.md'), {'type':'Build Document'}, name)
    write_doc(docs / 'questions.md', {'type':'Business Questions'}, '- q1: Revenue? (priority: high)')
    write_doc(docs / 'derived-fields.md', {'type':'Derived Fields','view':'project.data.view','fields':[],'joins':[]}, '')
    return docs.parent


@pytest.mark.parametrize('invalid', [0,1,3])
async def test_spec_repair_and_persistence(client, app, build_id, invalid):
    folder = spec_seed(app, build_id)
    fake = SpecLLM(invalid=invalid)
    if invalid == 3:
        with pytest.raises(RunError) as exc:
            await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=fake)
        assert exc.value.detail['errors'][0]['message'] == 'Unknown datasource field'
        assert not (folder / 'spec.json').exists()
        assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'interview'
    else:
        await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=fake)
        result = client.get(f'/api/builds/{build_id}/spec')
        assert result.status_code == 200
        assert result.json() == json.loads((folder / 'spec.json').read_text())
    assert fake.calls == (3 if invalid == 3 else invalid + 1)
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT * FROM traces').fetchall()
        assert len(traces) == 1
        assert traces[0]['status'] == ('error' if invalid == 3 else 'ok')


async def test_spec_prompt_allowlist(client, app, build_id, monkeypatch):
    spec_seed(app, build_id)
    monkeypatch.setenv('DSS_ALLOWED_TYPES','scorecard')
    class Narrow(SpecLLM):
        async def generate_content_async(self, llm_request, stream=False):
            assert llm_request.config.response_json_schema['$defs']['Component']['properties']['type']['enum'] == ['scorecard']
            assert '"component_type": "pie"' not in llm_request.config.system_instruction
            async for event in super().generate_content_async(llm_request, stream):
                yield event
    await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=Narrow())


def test_datasource_projection():
    fields = datasource_fields([{'columns':[{'name':'Order Date','type':'string','date_like':True},
        {'name':'Revenue','type':'number'}, {'name':'Revenue','type':'number'}]}], [])
    assert [f['name'] for f in fields] == ['order_date', 'revenue', 'revenue_2']
    assert fields[0]['type'] == 'DATE'


def test_missing_spec(client, build_id):
    assert client.get(f'/api/builds/{build_id}/spec').status_code == 409


@pytest.mark.parametrize('raw', ['not json', '{"pages": [', '[]'])
async def test_malformed_spec_exhausts_repairs(client, app, build_id, raw):
    folder = spec_seed(app, build_id)
    old = '{"previous": "saved"}'
    (folder / 'spec.json').write_text(old)
    fake = FakeLLM(response=raw)
    with pytest.raises(RunError):
        await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=fake)
    assert fake.calls == 3
    assert (folder / 'spec.json').read_text() == old


async def test_unsafe_spec_does_not_log_secrets(client, app, build_id, caplog):
    folder = spec_seed(app, build_id)
    with pytest.raises(RunError):
        await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=FakeLLM(response='{"title":"test-key"}'))
    assert 'test-key' not in caplog.text
    assert not (folder / 'spec.json').exists()


async def test_spec_budget_and_history(client, app, build_id):
    spec_seed(app, build_id)
    class Budget(SpecLLM):
        async def generate_content_async(self, llm_request, stream=False):
            assert len(llm_request.contents) == 1
            assert llm_request.contents[0].parts[0].text == 'Write the requested Dashboard Spec.'
            async for event in super().generate_content_async(llm_request, stream):
                yield event
    await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=Budget())
    with app.state.db.connect() as conn:
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE node='spec'").fetchone()[0])
    assert 0 < next(s['input_tokens_estimate'] for s in spans if s['node'] == 'spec') <= 16000


async def test_oversized_context_never_calls_model(client, app, build_id):
    folder = spec_seed(app, build_id)
    (folder / 'docs/brief.md').write_text('x' * 64001)
    fake = SpecLLM()
    with pytest.raises(RunError):
        await app.state.harness.run('spec', build_id, {'config':app.state.settings.get()}, llm=fake)
    assert fake.calls == 0


@pytest.mark.parametrize('invalid', [1, 3])
async def test_invalid_colors_use_bounded_repair_before_publication(client, app, build_id, invalid):
    folder = spec_seed(app, build_id)
    from test_spec_validate import sample
    previous = {'spec.json': json.dumps(sample()).encode(), 'prototype.html': b'previous prototype',
                'background_p1.png': b'previous background', 'recipe.jsonl': b'previous recipe'}
    for name, content in previous.items():
        (folder / name).write_bytes(content)
    class Colors(FakeLLM):
        async def generate_content_async(self, llm_request, stream=False):
            self.calls += 1
            schema = llm_request.config.response_json_schema
            props = schema['$defs']['Theme']['properties']
            assert props['palette']['items']['pattern'] == '^#[0-9A-Fa-f]{6}$'
            assert 'exactly #RRGGBB' in llm_request.config.system_instruction
            if self.calls > 1:
                for field in ('background', 'surface', 'text', 'muted', 'accent', 'palette.1'):
                    assert 'theme.' + field in llm_request.config.system_instruction
            spec = response_for(llm_request)
            spec['datasource']['synthetic'] = False
            if self.calls <= invalid:
                spec['theme'] = {field: '123456' for field in ('background', 'surface', 'text', 'muted', 'accent')}
                spec['theme']['palette'] = ['#123456', '#abc']
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=json.dumps(spec))]))
    fake = Colors()
    if invalid == 3:
        with pytest.raises(RunError) as error:
            await app.state.harness.run('spec', build_id, {'config': app.state.settings.get()}, llm=fake)
        assert error.value.code == 'invalid_request'
        assert {e['path'] for e in error.value.detail['errors']} == {
            'theme.' + field for field in ('background', 'surface', 'text', 'muted', 'accent', 'palette.1')}
        assert {name: (folder / name).read_bytes() for name in previous} == previous
        assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'interview'
    else:
        await app.state.harness.run('spec', build_id, {'config': app.state.settings.get()}, llm=fake)
        from dss.spec.validate import validate_spec
        assert validate_spec(json.loads((folder / 'spec.json').read_text())) == []
        assert all((folder / name).read_bytes() == content for name, content in previous.items() if name != 'spec.json')
    assert fake.calls == invalid + (invalid != 3)
    with app.state.db.connect() as conn:
        assert [row[0] for row in conn.execute('SELECT status FROM traces')] == ['error' if invalid == 3 else 'ok']
