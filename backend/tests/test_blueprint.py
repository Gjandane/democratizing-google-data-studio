"""15.6 oracle: generation, coverage repair, redraft retention and view validation."""
import asyncio
from copy import deepcopy
import csv
import json
from pathlib import Path
from types import SimpleNamespace

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
    # The shape fixture describes a richer source; use this oracle's actual CSV.
    for row in draft['rows']:
        if row['question_id'] == 'q5':
            row['component']['dimensions'] = ['product_category']
        if row['question_id'] == 'q7':
            row['component']['options']['row_dimensions'] = ['region']
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
    if remove:
        repair = deepcopy(next(r for r in value['rows'] if r['question_id'] == 'q7'))
        repair['component']['options']['column_dimensions'] = ['product_category']
        llm.replies.append(json.dumps({'rows': [repair]}))
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', bid))
    confirm(client, app, bid)
    assert llm.calls == (2 if remove else 1)
    assert node.load(folder).derived_fields == context.derived_fields
    assert ('>= 5' in bq.sql[-1]) != remove


def choose(client, bid, assessment, issue, alternative=None):
    return client.post(f'/api/builds/{bid}/feasibility/decisions', json={
        'assessment_id': assessment['id'], 'decisions': [{'issue_id': issue['id'],
            'action': 'accept_alternative' if alternative else 'drop', 'alternative_id': alternative}]})


def test_ratio_block_accept_gate_and_code_only_choice_survives_reload_redraft(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert assessment['state'] == 'blocked'
    ratio = next(i for i in assessment['issues'] if i['requirement'] == 'q2')
    assert ratio['status'] == 'unsupported_app'
    assert [a['id'] for a in ratio['alternatives']] == ['numerator_denominator']
    row = next(r for r in node.load(folder).rows if r.question_id == 'q2')
    assert row.status == 'blocked' and row.issue_ids == [ratio['id']]
    before = (folder / 'docs/blueprint.md').read_bytes()
    response = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    assert (folder / 'docs/blueprint.md').read_bytes() == before and not hasattr(bq, 'created')
    # Preflight refreshed the assessment id; choose against the current projection.
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    response = choose(client, bid, assessment, ratio, 'numerator_denominator')
    assert response.status_code == 200, response.text
    assert response.json()['state'] == 'ready' and llm.calls == 1
    rows = [r for r in node.load(folder).rows if r.question_id == 'q2']
    assert [m.model_dump() for r in rows for m in r.component.metrics] == [
        {'field': 'revenue', 'agg': 'sum'}, {'field': 'order_id', 'agg': 'count_distinct'}]
    assert all(r.status == 'ok' for r in rows)
    assert client.get(f'/api/builds/{bid}/feasibility').json()['state'] == 'ready'
    assert choose(client, bid, assessment, ratio).status_code == 409
    # Another question changes; q2's explicit decision and rows survive.
    outline = Outline.model_validate(fixture('outline'))
    outline.sections[1].questions[0].text += ' Please sort ascending.'
    artifact(folder, outline)
    changed = deepcopy(next(r for r in value['rows'] if r['question_id'] == 'q4'))
    llm.replies.append(json.dumps({**value, 'rows': [changed]}))
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', bid))
    confirm(client, app, bid)
    result = client.get(f'/api/builds/{bid}/feasibility').json()
    assert result['state'] == 'ready' and llm.calls == 2
    assert next(i for i in result['issues'] if i['id'] == ratio['id'])['resolution'] == 'accepted_alternative'


@pytest.mark.parametrize('date,extra_metric', [(None, False), ('missing_date', False), ('revenue', True)])
def test_no_date_one_repair_then_issue_and_alternative(blueprint_api, date, extra_metric):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    broken = next(r for r in value['rows'] if r['question_id'] == 'q3')
    broken['component']['date_dimension'] = date
    if extra_metric:
        broken['component']['metrics'].append({'field': 'quantity', 'agg': 'sum'})
    llm.replies = [json.dumps(value), json.dumps({'rows': [broken]})]
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    issue = next(i for i in assessment['issues'] if any(a['id'] == 'without_date' for a in i['alternatives']))
    assert llm.calls == 2 and issue['alternatives'][0]['id'] == 'without_date'
    response = choose(client, bid, assessment, issue, 'without_date')
    assert response.status_code == 200 and llm.calls == 2
    assert next(r for r in node.load(folder).rows if r.question_id == 'q3').component.type == ('table' if extra_metric else 'scorecard')


@pytest.mark.parametrize('repair_succeeds', [False, True])
def test_blueprint_extra_derived_type_must_match_dry_run(blueprint_api, repair_succeeds):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    value['derived_fields'].append({'name': 'fake_number', 'type': 'number',
        'expression': "'not numeric'", 'description': 'Must be numeric'})
    fixed = deepcopy(value['derived_fields'])
    if repair_succeeds:
        fixed[-1]['expression'] = '`revenue` * 0.9'
    llm.replies = [json.dumps(value), json.dumps({'view_sources': value['view_sources'], 'derived_fields': fixed})]
    def dry_run(sql):
        bq.sql.append(sql)
        return [SimpleNamespace(name='order_size_band', field_type='STRING', mode='NULLABLE'),
                SimpleNamespace(name='fake_number', field_type='STRING' if 'not numeric' in sql else 'FLOAT', mode='NULLABLE')]
    bq.dry_run = dry_run
    confirm(client, app, bid)
    assert llm.calls == 2 and len(bq.sql) == 2
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert any('SQL validation' in i['reason'] for i in assessment['issues']) != repair_succeeds
    assert (node.load(folder).view_table is not None) == repair_succeeds


def test_wrong_kpi_aggregation_is_rejected_after_one_repair(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    broken = next(r for r in value['rows'] if r['question_id'] == 'q4')
    broken['component']['metrics'][0]['agg'] = 'avg'
    llm.replies = [json.dumps(value), json.dumps({'rows': [broken]})]
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert llm.calls == 2
    assert any(i['requirement'] == 'q4' and 'confirmed field and aggregation' in i['reason'] for i in assessment['issues'])
    assert next(r for r in node.load(folder).rows if r.question_id == 'q4').status == 'blocked'


def test_drop_all_rows_rejects_accept_and_preserves_issue_history(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    outline = Outline.model_validate(fixture('outline'))
    for section in outline.sections:
        for q in section.questions:
            q.selected = q.id == 'q2'
    artifact(folder, outline)
    value['rows'] = [r for r in value['rows'] if r['question_id'] == 'q2']
    llm.replies = [json.dumps(value)]
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    response = choose(client, bid, assessment, assessment['issues'][0])
    assert response.status_code == 200 and response.json()['state'] == 'ready'
    assert response.json()['issues'][0]['resolution'] == 'dropped'
    assert node.load(folder).rows == [] and llm.calls == 1
    response = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert response.status_code == 409 and response.json()['error']['code'] == 'artifact_invalid'


def test_thirteen_rows_get_one_repair_capacity_issue_and_code_trim(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    outline = fixture('outline')
    question = outline['sections'][0]['questions'][0]
    outline['sections'] = [outline['sections'][0]]
    outline['sections'][0]['questions'] = [{**question, 'id': f'cap{i}', 'recommended': i < 12,
        'kpi_refs': ['net_revenue']} for i in range(13)]
    artifact(folder, Outline.model_validate(outline))
    design = Design.model_validate(fixture('design'))
    design.page_structure = 'single'
    artifact(folder, design)
    row = next(r for r in value['rows'] if r['question_id'] == 'q1')
    value['rows'] = [{**deepcopy(row), 'question_id': f'cap{i}'} for i in range(13)]
    llm.replies = [json.dumps(value), json.dumps({'rows': value['rows']})]
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    issue = next(i for i in assessment['issues'] if 'Too many components' in i['reason'])
    assert llm.calls == 2 and [a['id'] for a in issue['alternatives']] == ['trim']
    response = choose(client, bid, assessment, issue, 'trim')
    assert response.status_code == 200, response.text
    assert response.json()['state'] == 'ready' and len(node.load(folder).rows) == 12
    assert llm.calls == 2


def test_gps_no_join_has_one_source_and_union_options():
    from dss.spec import feasibility
    from dss.spec.capabilities import Checker, load_registry
    from dss.data.bigquery import prepare_csv
    sources = []
    for name in ('activity_summary', 'route_speeding_events'):
        _, schema, _ = prepare_csv((Path(__file__).parent / f'data/gps_{name}.csv').read_bytes())
        sources.append({'id': name, 'table': f'project.gps.{name}', 'columns': [
            {'name': f.name, 'type': f.field_type, 'bq_type': f.field_type} for f in schema]})
    context = fixture('context')
    context.update(datasets=[{'source_id': s['id'], 'summary': 'GPS data'} for s in sources], derived_fields=[], kpis=[])
    outline = fixture('outline')
    outline['sections'] = [outline['sections'][0]]
    outline['sections'][0]['questions'] = [{**outline['sections'][0]['questions'][0], 'id': 'gps', 'kpi_refs': []}]
    bp = fixture('blueprint')
    bp.update(view_sources={'base': sources[0]['id'], 'joins': [], 'union': []}, derived_fields=[])
    bp['rows'] = [deepcopy(bp['rows'][1])]
    bp['rows'][0]['question_id'] = 'gps'
    bp['rows'][0]['component']['metrics'] = [{'field': sources[0]['columns'][0]['name'], 'agg': 'count'}]
    snapshot = {'sources': sources, 'context': context, 'outline': outline, 'design': fixture('design'),
                'blueprint': bp, 'incoming': [], 'reference': None, 'definitions': {}, 'spec': None}
    checker = Checker(load_registry())
    assessment = req.evaluate(snapshot, req.Ledger(), checker)
    issue = next(i for i in assessment.issues if 'Multiple sources' in i.reason)
    assert {a.id for a in issue.alternatives} == {'source_activity_summary', 'source_route_speeding_events', 'union'}
    ledger = req.Ledger(assessment=assessment)
    updated, result, draft, fresh = feasibility.decide(snapshot, ledger, checker, req.Decisions(
        assessment_id=assessment.id, decisions=[req.DecisionInput(issue_id=issue.id,
            action='accept_alternative', alternative_id='union')]))
    assert result.state == 'ready' and draft.view_sources.union == ['route_speeding_events']
    assert draft.view_table is None and updated.blueprint_decisions


def test_blueprint_decision_file_bundle_rolls_back(blueprint_api, monkeypatch):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    paths = [folder / name for name in ('requirements.json', 'blueprint-inputs.json',
        'docs/blueprint.md', 'docs/feasibility.md', 'docs/index.md', 'docs/log.md')]
    before = {p: p.read_bytes() for p in paths}
    def fail(*args):
        raise OSError('simulated bundle write failure')
    monkeypatch.setattr(req, 'save', fail)
    with pytest.raises(OSError, match='simulated'):
        choose(client, bid, assessment, next(i for i in assessment['issues'] if i['requirement'] == 'q2'),
               'numerator_denominator')
    assert {p: p.read_bytes() for p in paths} == before
    assert not app.state.harness.active_builds and llm.calls == 1


def test_blueprint_check_preserves_blocks_and_registry_changes_recheck_choices(blueprint_api, monkeypatch):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    result = client.post(f'/api/builds/{bid}/feasibility/check')
    assert result.status_code == 202
    wait(app)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    ratio = next(i for i in assessment['issues'] if i['requirement'] == 'q2')
    response = choose(client, bid, assessment, ratio, 'numerator_denominator')
    assert response.status_code == 200 and response.json()['state'] == 'ready'
    monkeypatch.setenv('DSS_ALLOWED_TYPES', 'bar,time_series,pivot_table,date_range')
    response = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert any('disabled' in i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved')
    assert next(i for i in assessment['issues'] if i['id'] == ratio['id'])['resolution'] == 'accepted_alternative'
    assert llm.calls == 1 and not hasattr(bq, 'created')


def test_blueprint_component_binding_roles_options_and_dropdown():
    from dss.artifacts.models import BlueprintComponent
    from dss.spec.feasibility import component_errors
    from dss.spec.capabilities import Checker, load_registry
    checker = Checker(load_registry())
    fields = {'value': {'name': 'value', 'type': 'FLOAT64', 'role': 'metric'},
              'category': {'name': 'category', 'type': 'STRING', 'role': 'dimension'}}
    c = BlueprintComponent(type='bar', label='Test', dimensions=['category'],
        metrics=[{'field': 'value', 'agg': 'sum'}], date_dimension=None, breakdown=None,
        sort={'field': 'value', 'order': 'asc'}, options={})
    assert component_errors(c, fields, checker) == []
    c.options = {'animate': True}
    assert any('Option animate' in message for _, message, _ in component_errors(c, fields, checker))
    c.options = {}
    c.metrics[0].field = 'category'
    assert any('numeric' in message for _, message, _ in component_errors(c, fields, checker))
    c.metrics[0].agg = 'count_distinct'
    c.sort.field = 'category'
    assert component_errors(c, fields, checker) == []
    c.sort.field = 'value'
    assert any('Sort field' in message for _, message, _ in component_errors(c, fields, checker))
    c.type, c.metrics, c.sort = 'dropdown', [], None
    assert component_errors(c, fields, checker) == []
    c.type = 'pivot_table'
    for invalid in (None, 42, 'category', {'field': 'category'}):
        c.options = {'row_dimensions': invalid, 'column_dimensions': []}
        assert any(status == 'unsupported_app' for status, _, _ in component_errors(c, fields, checker))


def test_accept_cannot_grant_support_to_unprocessed_reference_intent(blueprint_api, monkeypatch):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    ratio = next(i for i in assessment['issues'] if i['requirement'] == 'q2')
    assert choose(client, bid, assessment, ratio, 'numerator_denominator').json()['state'] == 'ready'
    original = req.inputs
    def changed(*args):
        snapshot = original(*args)
        snapshot['incoming'].append(req.Source(id='new_ref:instructions', kind='reference', reference_id='new_ref',
            text='Animate GPS points along a route').model_dump())
        return snapshot
    monkeypatch.setattr(req, 'inputs', changed)
    before = (folder / 'docs/blueprint.md').read_bytes()
    response = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert any('not been assessed' in i['reason'] for i in assessment['issues'])
    assert llm.calls == 1 and (folder / 'docs/blueprint.md').read_bytes() == before
    assert not hasattr(bq, 'created')


@pytest.mark.parametrize('always_fails', [False, True])
def test_dry_run_has_exactly_one_structured_sql_repair(blueprint_api, always_fails):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    runs = []
    def dry_run(sql):
        runs.append(sql)
        if always_fails or len(runs) == 1:
            raise ValueError('Unrecognized name: invalid_field; test-key')
        return [SimpleNamespace(name='order_size_band', field_type='STRING', mode='NULLABLE')]
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
        return [SimpleNamespace(name='order_size_band', field_type='STRING', mode='NULLABLE')]
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


def test_catalog_summary_dropdown_slots_match_feasibility():
    """Live 15.11: the summary said 0 dropdown dimensions, feasibility required one."""
    from dss.artifacts.models import BlueprintComponent
    from dss.spec.capabilities import Checker, load_registry
    from dss.spec.feasibility import component_errors
    [entry] = [e for e in node.catalog_summary() if e['type'] == 'dropdown']
    assert (entry['min_dimensions'], entry['max_dimensions']) == (1, 1)
    assert 'field' not in entry['slot_roles'] and entry['slot_roles']['dimensions'] == ['dimension']
    fields = {'region': {'role': 'dimension', 'type': 'STRING'}}
    def errors(dimensions):
        return component_errors(BlueprintComponent(type='dropdown', label='Region', dimensions=dimensions, metrics=[],
            date_dimension=None, breakdown=None, sort=None, options={}), fields, Checker(load_registry()))
    assert errors(['region']) == [] and errors([])


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


def test_leaked_label_syntax_is_repaired_to_its_first_fragment_without_a_model_call(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    index = next(i for i, r in enumerate(value['rows']) if r['question_id'])
    value['rows'][index]['component']['label'] = "Total Population (M)','Total Nominal GDP (USD M) - Population"
    llm.replies = [json.dumps(value)]
    confirm(client, app, bid)
    draft = client.get(f'/api/builds/{bid}/blueprint').json()
    assert llm.calls == 1
    assert draft['rows'][index]['component']['label'] == 'Total Population (M)'
    assert "','" not in (folder / 'docs/blueprint.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('repair_succeeds', [False, True])
def test_label_without_a_clean_fragment_goes_through_the_one_row_repair(blueprint_api, repair_succeeds):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    index = next(i for i, r in enumerate(value['rows']) if r['question_id'])
    qid = value['rows'][index]['question_id']
    value['rows'][index]['component']['label'] = "['', '']"
    repaired = deepcopy([r for r in value['rows'] if r['question_id'] == qid])
    repaired[0]['component']['label'] = 'Net revenue' if repair_succeeds else '"'
    llm.replies = [json.dumps(value), json.dumps({'rows': repaired})]
    confirm(client, app, bid)
    draft = client.get(f'/api/builds/{bid}/blueprint').json()
    assert llm.calls == 2
    assert 'without list or quote syntax' in str(llm.seen[1].config.system_instruction)
    labels = [r['component']['label'] for r in draft['rows'] if r['question_id'] == qid]
    metric = repaired[0]['component']['metrics'][0]['field'].replace('_', ' ')
    assert labels[0] == 'Net revenue' if repair_succeeds else labels[0].lower().startswith(metric)
    assert all(label and node.label_text(label) == label for label in labels)
    # Label syntax is code-repaired, never a persisted feasibility issue.
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert not any('quote syntax' in i['reason'] for i in assessment['issues'])


@pytest.mark.parametrize('leaked', ['DATE_TRUNC(year, YEAR) /* o3, o5, o6 */', "DATE_TRUNC(year, YEAR)','date',",
                                    "DATE_TRUNC(year, YEAR)', 'date'", "DATE_TRUNC(year, YEAR)','type':'date"])
def test_a_leaked_expression_tail_is_dropped_and_the_gate_still_holds(leaked):
    """Live 24.7 runs (and 24.8 run 20261025-215617, a key:value tail): the planner cited observation ids in a
    trailing SQL comment, or leaked the next JSON field into the string; the one SQL repair did not fix either. Code drops the tail, nothing else."""
    from dss.artifacts.models import DerivedField
    from dss.harness.nodes import view
    field = DerivedField(name='year_bucket', expression=leaked, type='date', description='Year')
    [kept] = node.derived_fields(Context.model_validate(fixture('context')).model_copy(update={'derived_fields': []}), [field])
    assert kept.expression == 'DATE_TRUNC(year, YEAR)'
    for unsafe in ('DATE_TRUNC(year, YEAR) /* x */ + 1', 'a /* x */ /* y */', "x', 'y' OR 1=1"):
        with pytest.raises(ValueError):
            view.expression(view.model_expression(unsafe))
