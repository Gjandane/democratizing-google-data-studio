"""Context oracle: code-owned validation, bounded repair, API/state and working memory."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient
from google.adk.models.llm_request import LlmRequest
from google.genai import types
import pytest

from dss.artifacts.models import Context
from dss.artifacts.okf import read_artifact
from dss.config import Config
from dss.harness.context import Section, assemble, context_draft_context, fit_request
from dss.harness.guardrails import RunError
from dss.harness.nodes.context import validate
from dss.main import create_app
from fakes import FakeLLM, fake_models
from test_api_contract import FIXTURES, check
from test_intake import FakeBigQuery as IntakeBigQuery, create, upload


class FakeBigQuery(IntakeBigQuery):
    def __init__(self):
        super().__init__()
        self.sql = []
        self.fail = False

    def dry_run(self, sql):
        self.sql.append(sql)
        if self.fail or 'unknown_column' in sql:
            raise RuntimeError('sensitive provider text must not escape')
        return [SimpleNamespace(name='order_size_band', field_type='STRING', mode='NULLABLE'),
                SimpleNamespace(name='net', field_type='FLOAT', mode='NULLABLE')]


class ContextLLM(FakeLLM):
    replies: list[str] = []
    seen: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.seen.append(llm_request.model_copy(deep=True))
        self.response = self.replies[min(self.calls, len(self.replies) - 1)]
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def wait(app):
    deadline = time.monotonic() + 15
    while app.state.engine_tasks or app.state.harness.active_builds:
        assert time.monotonic() < deadline, 'Context run did not finish'
        time.sleep(.01)


def example(source='s_example'):
    draft = json.loads((FIXTURES / 'context.json').read_text(encoding='utf-8'))
    draft['datasets'][0]['source_id'] = source
    return draft


CONNECTED = [{'id': 's_example', 'name': 'sales', 'bq_table': 'test-project.data.sales', 'row_count': 4,
              'columns': [{'name': name, 'type': kind, 'sample': []} for name, kind in (
                  ('quantity', 'number'), ('revenue', 'number'), ('order_id', 'string'), ('date', 'date'))]}]


@pytest.fixture
def context_api(tmp_path):
    bq = FakeBigQuery()
    app = create_app(Config(data_dir=tmp_path, google_api_key='test-key', gcp_project_id='test-project'),
                     model_lister=fake_models, bigquery_factory=lambda _: bq)
    with TestClient(app) as client:
        build = create(client)
        sales = (Path(__file__).parent / 'data/interview_sales.csv').read_bytes()
        assert upload(client, build['id'], files=[('files', ('sales.csv', sales, 'text/csv'))]).status_code == 201
        source = client.get(f'/api/builds/{build["id"]}').json()['sources'][0]
        folder = tmp_path / 'builds' / build['id'] / 'v1'
        yield client, app, build['id'], source['id'], folder, bq


def editable(draft):
    return {k: v for k, v in draft.items() if k not in ('revision', 'issues')}


def test_valid_validation_one_combined_dry_run():
    fake = FakeBigQuery()
    data = example()
    data['derived_fields'].append({'name': 'net', 'expression': '`revenue` * 0.9', 'type': 'number', 'description': 'Net assumption'})
    result = validate(Context.model_validate(data), CONNECTED, lambda: fake)
    assert result.issues == []
    assert len(fake.sql) == 1
    assert ' AS `order_size_band`' in fake.sql[0] and ' AS `net`' in fake.sql[0]


def test_actual_derived_type_is_checked_before_numeric_use():
    data = example()
    data['derived_fields'][0].update(expression="'text'", type='number')
    data['kpis'][0]['measure']['field'] = 'order_size_band'
    data['thresholds'][0]['field'] = 'order_size_band'
    result = validate(Context.model_validate(data), CONNECTED, FakeBigQuery)
    assert '/derived_fields/0/type' in [issue.path for issue in result.issues]


@pytest.mark.parametrize('change,path', [
    (lambda d: d['kpis'][0]['measure'].update(field='missing'), '/kpis/0/measure/field'),
    (lambda d: d['derived_fields'][0].update(expression='SUM(revenue)'), '/derived_fields/0/expression'),
    (lambda d: d['derived_fields'][0].update(expression='row_number() OVER ()'), '/derived_fields/0/expression'),
    (lambda d: d['derived_fields'][0].update(expression='COUNTIF(quantity > 0)'), '/derived_fields/0/expression'),
    (lambda d: d['derived_fields'][0].update(expression='unknown_column * 2'), '/derived_fields/0/expression'),
    (lambda d: d['kpis'][0]['measure'].update(field='order_id'), '/kpis/0/measure/agg'),
    (lambda d: d['kpis'][0]['measure'].update(field='order_id', agg='min'), '/kpis/0/measure/agg'),
    (lambda d: d['kpis'][3]['ratio'].update(numerator='missing'), '/kpis/3/ratio/numerator'),
    (lambda d: d['kpis'][3]['ratio'].update(denominator='avg_order_value'), '/kpis/3/ratio/denominator'),
    (lambda d: d['thresholds'][0].update(field='order_id'), '/thresholds/0/field'),
    (lambda d: d['thresholds'][0].update(id='Bad ID'), '/thresholds/0/id'),
    (lambda d: d['thresholds'][0].update(id='net_revenue'), '/thresholds/0/id'),
    (lambda d: d['derived_fields'][0].update(name='revenue'), '/derived_fields/0/name'),
    (lambda d: d['datasets'][0].update(source_id='missing'), '/datasets/0/source_id'),
])
def test_invalid_paths(change, path):
    data = example()
    change(data)
    result = validate(Context.model_validate(data), CONNECTED, FakeBigQuery)
    assert path in [issue.path for issue in result.issues]
    assert 'sensitive provider' not in result.model_dump_json()


@pytest.mark.parametrize('group,limit', [('kpis', 15), ('derived_fields', 15), ('thresholds', 15), ('glossary', 30)])
def test_limits(group, limit):
    data = example()
    data[group] = [deepcopy(data[group][0]) for _ in range(limit + 1)]
    result = validate(Context.model_validate(data), CONNECTED, FakeBigQuery)
    assert '/' + group in [i.path for i in result.issues]


@pytest.mark.parametrize('agg', ['count', 'count_distinct'])
def test_count_accepts_string(agg):
    data = example()
    data['kpis'][0]['measure'].update(field='order_id', agg=agg)
    assert validate(Context.model_validate(data), CONNECTED, FakeBigQuery).issues == []


def test_draft_edit_confirm_and_events(context_api, monkeypatch):
    client, app, bid, sid, folder, bq = context_api
    url = f'/api/builds/{bid}/context'
    assert client.get(url).json() is None
    llm = ContextLLM(replies=[json.dumps(example(sid))])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    response = client.post(url, json={'notes': 'Net revenue, distinct orders; weekly review by the sales director.'})
    check(response, 'run_accepted.json', 202)
    wait(app)
    assert client.get(url).status_code == 200
    draft = client.get(url).json()
    assert draft.keys() == example(sid).keys()
    assert Context.model_validate(draft).model_dump(mode='json') == draft
    assert draft['issues'] == [] and draft['revision'] == 1 and llm.calls == 1
    assert read_artifact(folder / 'docs/context.md').model_dump(mode='json') == draft
    built = client.get(f'/api/builds/{bid}').json()
    assert built['artifacts']['context'] == 'draft' and built['stage'] == 'context'
    assert built['notes'].startswith('Net revenue')
    assert 'Context drafted' in client.get(f'/api/builds/{bid}/messages').json()[-1]['text']
    body = editable(draft)
    body['kpis'][0]['measure']['field'] = 'missing'
    response = client.put(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 2 and response.json()['issues'][0]['path'] == '/kpis/0/measure/field'
    invalid = client.post(url + '/confirm')
    assert invalid.status_code == 409 and invalid.json()['error']['code'] == 'artifact_invalid'
    body['kpis'][0]['measure']['field'] = 'revenue'
    assert client.put(url, json=body).json()['issues'] == []
    assert llm.calls == 1
    accepted = client.post(url + '/confirm')
    check(accepted, 'run_accepted.json', 202)
    wait(app)
    built = client.get(f'/api/builds/{bid}').json()
    assert built['stage'] == 'outline' and built['artifacts']['context'] == 'confirmed'
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT * FROM traces WHERE run_id IN (?,?)', (response.json().get('run_id'), accepted.json()['run_id'])).fetchall()
        events = [r[0] for r in conn.execute('SELECT kind FROM events WHERE build_id=?', (bid,))]
    assert len(traces) == 1 and traces[0]['status'] == 'ok' and traces[0]['node'] == 'outline_propose'
    assert {'artifact.updated', 'docs.updated', 'stage.changed', 'message.done'} <= set(events)


@pytest.mark.parametrize('repaired', [False, True])
def test_at_most_one_repair_and_no_history(context_api, monkeypatch, repaired):
    client, app, bid, sid, folder, _ = context_api
    bad = example(sid)
    bad['kpis'][0]['measure']['field'] = 'missing'
    llm = ContextLLM(replies=[json.dumps(bad), json.dumps(example(sid) if repaired else bad)])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    from dss.memory import episodic
    episodic.save(app.state.db, bid, 'user', 'PRIVATE MESSAGE SENTINEL', 'old')
    response = client.post(f'/api/builds/{bid}/context', json={'notes': 'NOTE SENTINEL'})
    wait(app)
    draft = client.get(f'/api/builds/{bid}/context').json()
    assert bool(draft['issues']) != repaired and llm.calls == 2
    for req in llm.seen:
        assert req.config.max_output_tokens == 3000
        assert len(req.contents) == 1 and 'PRIVATE MESSAGE SENTINEL' not in str(req)
    repair = llm.seen[-1].config.system_instruction
    assert 'NOTE SENTINEL' not in repair and 'Aggregate profile' not in repair
    assert '/kpis/0/measure/field' in repair
    with app.state.db.connect() as conn:
        row = conn.execute('SELECT * FROM traces WHERE run_id=?', (response.json()['run_id'],)).fetchone()
    assert row['status'] == 'ok'
    spans = json.loads(row['spans_json'])
    assert len([s for s in spans if s['node'] == 'context_repair']) == 1


def test_structural_repair_and_bounded_failure(context_api, monkeypatch):
    client, app, bid, sid, folder, _ = context_api
    invalid = example(sid)
    invalid['kpis'][0]['ratio'] = {'numerator': 'orders', 'denominator': 'units_sold'}
    llm = ContextLLM(replies=[json.dumps(invalid)])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    response = client.post(f'/api/builds/{bid}/context')
    wait(app)
    assert llm.calls == 2 and not (folder / 'docs/context.md').exists()
    with app.state.db.connect() as conn:
        row = conn.execute('SELECT * FROM traces WHERE run_id=?', (response.json()['run_id'],)).fetchone()
    assert row['status'] == 'error'


def test_stages_lock_and_input(context_api, monkeypatch):
    client, app, bid, sid, folder, _ = context_api
    url = f'/api/builds/{bid}/context'
    assert client.post(url, json={'notes': 'x' * 4001}).status_code == 422
    assert client.post(url, json={'notes': None}).status_code == 422
    assert client.put(url, json=example(sid)).status_code == 422
    for stage in ('build', 'done', 'outline'):
        with app.state.db.connect() as conn:
            conn.execute('UPDATE builds SET stage=? WHERE id=?', (stage, bid))
        assert client.post(url).status_code == 409
        if stage != 'outline':
            assert client.put(url, json=editable(example(sid))).status_code == 409
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='context' WHERE id=?", (bid,))
    app.state.harness.active_builds.add(bid)
    assert client.post(url).status_code == 409
    assert client.put(url, json=editable(example(sid))).status_code == 409
    assert client.post(url + '/confirm').status_code == 409
    app.state.harness.active_builds.discard(bid)
    assert client.get('/api/builds/b_missing/context').status_code == 404
    empty = create(client)
    assert client.post(f'/api/builds/{empty["id"]}/context').status_code == 409


def test_earlier_edit_stales_downstream(context_api):
    client, app, bid, sid, folder, _ = context_api
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=?,artifacts_json=? WHERE id=?', ('prototype', json.dumps({
            k: 'confirmed' for k in ('context', 'outline', 'design', 'blueprint')}), bid))
    (folder / 'prototype.html').write_text('published', encoding='utf-8')
    response = client.put(f'/api/builds/{bid}/context', json=editable(example(sid)))
    assert response.status_code == 200
    built = client.get(f'/api/builds/{bid}').json()
    assert built['stage'] == 'context'
    assert built['artifacts'] == {'context': 'draft', 'outline': 'stale', 'design': 'stale', 'blueprint': 'stale'}
    assert (folder / 'prototype.html').read_text(encoding='utf-8') == 'published'


def test_assembly_no_rows_and_drop_order():
    source = deepcopy(CONNECTED[0])
    source['rows'] = [{'PRIVATE_ROW': 'must never be read'}]
    context = context_draft_context(None, [source], 'Compare revenue', 'executive')
    assert [s.kind for s in context.sections] == ['system', 'skills', 'skills', 'semantic', 'profile', 'input']
    assert 'PRIVATE_ROW' not in context and 'history' not in [s.kind for s in context.sections]
    sections = [Section('system', 's', body='s'), Section('skills', 'k', body='k'),
                Section('semantic', 'first', body='f'), Section('semantic', 'second', body='b' * 1000),
                Section('profile', 'p', body='p' * 2000, compact='p' * 100),
                Section('reference', 'r', body='r' * 1000), Section('input', 'i', body='notes')]
    fitted = assemble('context', sections, reserve=9600)
    assert fitted.dropped['profile'] == 1 and fitted.dropped['reference'] == 1 and fitted.dropped['semantic'] == 0
    with pytest.raises(RunError):
        assemble('context', [Section('input', 'input', body='x' * 40001)])


async def test_counting_failure_and_conservative_bound():
    class Counted(FakeLLM):
        async def count_request_tokens(self, request):
            return 8000
    context = assemble('context', [Section('input', 'i', body='small')])
    req = LlmRequest(model='fake', config=types.GenerateContentConfig(system_instruction=str(context)))
    span = {}
    with pytest.raises(RunError):
        await fit_request(context, req, Counted(), span)
    assert span['folded_request_tokens'] == 8000 and span['enforced_input_bound'] == 10112
    assert span['request_tokens'] is None
    class Failed(FakeLLM):
        async def count_request_tokens(self, request):
            raise RuntimeError('secret')
    with pytest.raises(RunError, match='could not be counted'):
        await fit_request(context, req, Failed(), {})
