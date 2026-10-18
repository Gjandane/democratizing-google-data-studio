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
