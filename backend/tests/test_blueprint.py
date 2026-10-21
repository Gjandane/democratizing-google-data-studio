"""15.6 oracle: generation, coverage repair, redraft retention and view validation."""
import asyncio
from copy import deepcopy
import csv
import json
from pathlib import Path

import pytest

from dss.artifacts import state as stages
from dss.artifacts import design as design_node
from dss.artifacts.models import Blueprint, Context, Design, Outline
from dss.artifacts.okf import write_artifact
from dss.harness.context import BUDGETS, blueprint_context, fit_request
from dss.harness.guardrails import RunError
from dss.harness.nodes import blueprint as node
from dss.spec import requirements as req
from test_api_contract import FIXTURES
from test_context_node import context_api, ContextLLM, wait


def fixture(name):
    value = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
    if name == 'design':
        value['font_family'] = design_node.presets()[0].font_family
    return value


async def ignore(*args):
    pass


def artifact(folder, value):
    name = type(value).__name__.lower()
    asyncio.run(write_artifact(folder / f'docs/{name}.md', value, emit=ignore))


@pytest.fixture
def blueprint_api(context_api, monkeypatch):
    client, app, bid, sid, folder, bq = context_api
    context = fixture('context')
    context['datasets'][0]['source_id'] = sid
    artifact(folder, Context.model_validate(context))
    artifact(folder, Outline.model_validate(fixture('outline')))
    artifact(folder, Design.model_validate(fixture('design')))
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=?, artifacts_json=? WHERE id=?', ('design', json.dumps({
            'context': 'confirmed', 'outline': 'confirmed', 'design': 'draft', 'blueprint': 'missing'}), bid))
    draft = fixture('blueprint')
    draft['view_sources']['base'] = sid
    # q1 names three KPI definitions: three scorecards are legal rows for one question.
    for field, agg in [('order_id', 'count_distinct'), ('quantity', 'sum')]:
        row = deepcopy(draft['rows'][1])
        row['component']['metrics'] = [{'field': field, 'agg': agg}]
        draft['rows'].append(row)
    value = {k: draft[k] for k in ('view_sources', 'derived_fields', 'rows')}
    llm = ContextLLM(replies=[json.dumps(value)])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    return client, app, bid, sid, folder, bq, llm, value


def confirm(client, app, bid):
    result = client.post(f'/api/builds/{bid}/design/confirm')
    assert result.status_code == 202, result.text
    wait(app)
    return result.json()['run_id']


def test_ecommerce_rows_pages_contract_trace_and_metadata_only(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    assert client.get(f'/api/builds/{bid}/blueprint').json() is None
    run_id = confirm(client, app, bid)
    result = client.get(f'/api/builds/{bid}/blueprint').json()
    assert result is not None
    assert result.keys() == fixture('blueprint').keys()
    assert Blueprint.model_validate(result).model_dump(mode='json') == result
    selected = {q['id'] for s in fixture('outline')['sections'] for q in s['questions'] if q['selected']}
    assert {r['question_id'] for r in result['rows'] if r['question_id']} == selected
    assert all(r['page'] == (1 if r['section_id'] == 's1' else 2) for r in result['rows'])
    assert result['view_table'].endswith(run_id) and len(bq.sql) == 1
    assert llm.calls == 1 and result['revision'] == 1
    request = llm.seen[0]
    instruction = str(request.config.system_instruction)
    assert 'Allowed catalog types, slots and options' in instruction and 'max_metrics' in instruction
    assert 'row_count' not in instruction and 'sample' not in instruction and 'O-1001' not in instruction
    assert 'history' not in instruction and 'messages' not in instruction
    assert request.config.max_output_tokens == 6000
    assert request.contents[0].parts[0].text == 'Return the requested Blueprint draft JSON only.'
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchall()
        events = conn.execute('SELECT kind,payload_json FROM events WHERE run_id=?', (run_id,)).fetchall()
    assert len(traces) == 1 and traces[0]['status'] == 'ok'
    assert any(e['kind'] == 'artifact.updated' and json.loads(e['payload_json'])['artifact'] == 'blueprint' for e in events)
    assert not hasattr(bq, 'created')  # only a dry run, no candidate DDL
    assert client.get(f'/api/builds/{bid}').json()['artifacts']['design'] == 'confirmed'


@pytest.mark.parametrize('repair_succeeds', [False, True])
def test_missing_question_one_row_repair_then_issue(blueprint_api, repair_succeeds):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    missing = [r for r in value['rows'] if r['question_id'] == 'q4']
    value['rows'] = [r for r in value['rows'] if r['question_id'] != 'q4']
    llm.replies = [json.dumps(value), json.dumps({'rows': missing if repair_succeeds else []})]
    confirm(client, app, bid)
    draft = client.get(f'/api/builds/{bid}/blueprint').json()
    assert draft is not None and llm.calls == 2
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert any(i['requirement'] == 'q4' for i in assessment['issues']) != repair_succeeds
    assert any(r['question_id'] == 'q4' for r in draft['rows']) == repair_succeeds
    repair = str(llm.seen[1].config.system_instruction)
    assert 'Which regions bring' in repair and 'Which product categories' not in repair


def test_redraft_sends_only_changed_question_and_keeps_rows(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    original = node.load(folder)
    outline = Outline.model_validate(fixture('outline'))
    outline.sections[1].questions[0].text = 'Which regions have the lowest net revenue?'
    artifact(folder, outline)
    # Simulate the already confirmed upstream edit, then a design reconfirmation.
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', bid))
    replacement = deepcopy(next(r for r in value['rows'] if r['question_id'] == 'q4'))
    replacement['component']['sort']['order'] = 'asc'
    replacement['page'] = 99
    llm.replies.append(json.dumps({**value, 'rows': [replacement]}))
    confirm(client, app, bid)
    revised = node.load(folder)
    assert llm.calls == 2 and revised.revision == 2
    assert [r for r in original.rows if r.question_id != 'q4'] == [r for r in revised.rows if r.question_id != 'q4']
    assert next(r for r in revised.rows if r.question_id == 'q4').page == 2
    sent = str(llm.seen[-1].config.system_instruction)
    assert 'Which regions have the lowest' in sent and 'What is the average order value?' not in sent
    # No changes: revalidate with zero further generations.
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', bid))
    confirm(client, app, bid)
    assert llm.calls == 2 and node.load(folder).revision == 3


@pytest.mark.parametrize('remove', [False, True])
def test_context_derivation_updates_survive_row_retention(blueprint_api, remove):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    context = Context.model_validate(fixture('context'))
    if remove:
        context.derived_fields = []
    else:
        context.derived_fields[0].expression = "CASE WHEN `quantity` >= 5 THEN 'Bulk' ELSE 'Single' END"
    artifact(folder, context)
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', bid))
    confirm(client, app, bid)
    assert llm.calls == 1
    assert node.load(folder).derived_fields == context.derived_fields
    assert ('>= 5' in bq.sql[-1]) != remove


@pytest.mark.parametrize('always_fails', [False, True])
def test_dry_run_has_exactly_one_structured_sql_repair(blueprint_api, always_fails):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    runs = []
    def dry_run(sql):
        runs.append(sql)
        if always_fails or len(runs) == 1:
            raise ValueError('Unrecognized name: invalid_field; test-key')
        return []
    bq.dry_run = dry_run
    llm.replies.append(json.dumps({k: value[k] for k in ('view_sources', 'derived_fields')}))
    confirm(client, app, bid)
    result = node.load(folder)
    assert result is not None and llm.calls == 2 and len(runs) == 2
    assert (result.view_table is None) == always_fails
    repair = str(llm.seen[-1].config.system_instruction)
    assert 'Unrecognized name: invalid_field' in repair and 'test-key' not in repair
    assert 'Which regions bring' not in repair
    assert any(i.requirement == 'Blueprint view' for i in req.load(folder).assessment.issues) == always_fails


def test_regenerate_all_rows_deselection_and_single_page(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    design = Design.model_validate(fixture('design'))
    design.page_structure = 'single'
    artifact(folder, design)
    outline = Outline.model_validate(fixture('outline'))
    outline.sections[0].questions[1].selected = False
    artifact(folder, outline)
    llm.replies.append(json.dumps(value))
    response = client.post(f'/api/builds/{bid}/blueprint/regenerate')
    assert response.status_code == 202
    wait(app)
    result = node.load(folder)
    assert llm.calls == 2 and all(r.page == 1 for r in result.rows)
    assert not any(r.question_id == 'q2' for r in result.rows)
    assert 'Which regions bring' in str(llm.seen[-1].config.system_instruction)


def test_api_stage_and_invalid_design_guards(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    assert client.post(f'/api/builds/{bid}/blueprint/regenerate').status_code == 409
    design = Design.model_validate(fixture('design'))
    design.font_family = 'Unavailable font'
    artifact(folder, design)
    assert client.post(f'/api/builds/{bid}/design/confirm').json()['error']['code'] == 'artifact_invalid'
    assert llm.calls == 0


def test_combined_row_and_sql_repairs_stay_in_three_call_cap(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    missing = next(r for r in value['rows'] if r['question_id'] == 'q4')
    value['rows'].remove(missing)
    llm.replies = [json.dumps(value), json.dumps({'rows': [missing]}),
                   json.dumps({k: value[k] for k in ('view_sources', 'derived_fields')})]
    calls = []
    def dry_run(sql):
        calls.append(sql)
        if len(calls) == 1:
            raise ValueError('Unknown field')
    bq.dry_run = dry_run
    confirm(client, app, bid)
    assert llm.calls == 3 and len(calls) == 2 and node.load(folder).view_table


async def test_counted_blueprint_request_enforces_conservative_14k_bound():
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    from dss.harness.context import assemble, Section
    class Counted(ContextLLM):
        async def count_request_tokens(self, request):
            return 12000  # folded allowance becomes 14912, above the 14k ceiling
    request = LlmRequest(model='fake', config=types.GenerateContentConfig())
    memory = assemble('blueprint', [Section('input', 'i', body='small')])
    span = {}
    with pytest.raises(RunError):
        await fit_request(memory, request, Counted(), span)
    assert span['folded_request_tokens'] == 12000 and span['enforced_input_bound'] == 14912
    assert span['request_tokens'] is None


def test_failed_regeneration_retains_previous_artifact(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    before = (folder / 'docs/blueprint.md').read_bytes()
    llm.replies.append('bad JSON')
    response = client.post(f'/api/builds/{bid}/blueprint/regenerate')
    assert response.status_code == 202
    wait(app)
    assert (folder / 'docs/blueprint.md').read_bytes() == before
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (response.json()['run_id'],)).fetchone()
    assert trace['status'] == 'error' and trace['error'] == 'llm_unavailable'


def test_compact_inputs_exclude_profile_payloads_and_join_facts():
    connected = [{'id': sid, 'bq_table': f'project.data.{sid}', 'rows': [{'SECRET_ROW': 1}],
        'columns': [{'name': 'order', 'type': 'number', 'bq_type': 'INTEGER', 'sample': ['SECRET_VALUE']}]} for sid in ('a', 'b')]
    metadata = node.source_metadata(connected)
    assert 'SECRET' not in json.dumps(metadata)
    assert node.join_facts(metadata) == [{'left_source': 'a', 'right_source': 'b', 'field': 'order', 'type': 'INT64'}]
    memory = blueprint_context(Context.model_validate(fixture('context')), metadata, [], {}, node.catalog_summary(), [])
    assert memory.node == 'blueprint' and BUDGETS['blueprint'] == 14000
    assert all(s.kind != 'history' for s in memory.sections)


def test_gps_fixtures_small_distinct_schemas_and_union():
    from dss.data.bigquery import prepare_csv
    from dss.artifacts.models import ViewSources
    from dss.harness.nodes.view import blueprint_sql
    connected = []
    for name in ('activity_summary', 'route_speeding_events'):
        content = (Path(__file__).parent / f'data/gps_{name}.csv').read_bytes()
        rows = list(csv.DictReader(content.decode().splitlines()))
        assert 1 <= len(rows) <= 50
        _, schema, _ = prepare_csv(content)
        connected.append({'id': name, 'bq_table': f'project.gps.{name}', 'columns': [
            {'name': f.name, 'bq_type': f.field_type} for f in schema]})
    sql = blueprint_sql(connected, ViewSources(base='activity_summary', joins=[], union=['route_speeding_events']), [])
    assert 'CAST(NULL AS FLOAT64) AS `speed_kph`' in sql and 'dataset_name' in sql and 'UNION ALL' in sql
