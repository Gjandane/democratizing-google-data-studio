"""Graph oracle: every action's branch runs one Workflow and records its nodes, in order, in
exactly one trace (architecture.md#Graph, change staged workflow 2026-10-21)."""
import json

import pytest

from dss.harness.guardrails import RunError
from dss.spec import references
from fakes import FakeLLM
from test_blueprint import blueprint_api  # noqa: F401  (fixture)
from test_context_node import ContextLLM, context_api, wait  # noqa: F401
from test_outline import outline_api, proposal, question  # noqa: F401
from test_references import STYLE, output, png
from test_render import blueprint_flow  # noqa: F401
from test_research import setup as research_build  # noqa: F401
from test_revise import RevisionModel, op, response, seed_revision

ARTIFACTS = ('context', 'outline', 'design', 'blueprint')


def trace(app, run_id):
    with app.state.db.connect() as conn:
        rows = conn.execute('SELECT node, status, spans_json FROM traces WHERE run_id=?', (run_id,)).fetchall()
    assert len(rows) == 1, f'{run_id}: {len(rows)} traces'
    return rows[0]['node'], rows[0]['status'], [s['node'] for s in json.loads(rows[0]['spans_json'])]


def by_node(app, node):
    with app.state.db.connect() as conn:
        runs = [r[0] for r in conn.execute('SELECT run_id FROM traces WHERE node=? ORDER BY rowid', (node,))]
    return [trace(app, run_id) for run_id in runs]


def accepted(response):
    assert response.status_code == 202, response.text
    return response.json()['run_id']


def ok(node, *spans):
    return node, 'ok', ['router', *spans, 'guardrail']


def test_context_and_outline_branches(outline_api):
    client, app, bid, sid, folder, llm = outline_api
    assert by_node(app, 'create_build') == [ok('create_build', 'create_build')]
    assert by_node(app, 'intake') == [ok('intake', 'intake')]
    assert by_node(app, 'context') == [ok('context', 'context', 'validate_context')]
    assert by_node(app, 'outline_propose') == [ok('outline_propose', 'outline_propose', 'validate_outline')]
    url = f'/api/builds/{bid}/outline'
    s1 = client.get(url).json()['sections'][0]['id']
    llm.replies.append(json.dumps({'questions': [question('Extra insight')]}))
    run = accepted(client.post(url + '/suggest', json={'section_id': s1}))
    wait(app)
    assert trace(app, run) == ok('outline_suggest', 'outline_suggest', 'validate_outline')
    llm.replies.append(json.dumps({'questions': [question('Revenue by weekday')], 'requirements': []}))
    run = accepted(client.post(url + '/other', json={'section_id': s1, 'text': 'Revenue by weekday'}))
    wait(app)
    assert trace(app, run) == ok('outline_other', 'outline_other', 'validate_outline')
    llm.replies.append(json.dumps(proposal()))
    run = accepted(client.post(url + '/propose'))
    wait(app)
    assert trace(app, run) == ok('outline_propose', 'outline_propose', 'validate_outline')
    # Re-confirming the Context revalidates the Outline in code: no model node.
    calls = llm.calls
    assert client.put(f'/api/builds/{bid}/context', json={k: v for k, v in client.get(
        f'/api/builds/{bid}/context').json().items() if k not in ('revision', 'issues')}).status_code == 200
    run = accepted(client.post(f'/api/builds/{bid}/context/confirm'))
    wait(app)
    assert trace(app, run) == ok('outline_propose', 'outline_propose') and llm.calls == calls


def test_blueprint_prototype_versions_and_recipe(blueprint_flow):
    client, app, bid, folder, bq, run_id = blueprint_flow
    assert by_node(app, 'blueprint') == [
        ok('blueprint', 'blueprint', 'validate_blueprint_rows', 'validate_blueprint_view')]
    # This flow's model answers the designer with Blueprint JSON: page 1 falls back to the code path.
    assert trace(app, run_id) == ok('prototype', 'prototype', 'view', 'layout', 'designer', 'validate',
                                    'designer', 'validate', 'designer_fallback', 'render', 'publish')
    build = client.get(f'/api/builds/{bid}').json()
    assert build['stage'] == 'prototype' and set(build['artifacts'].values()) == {'confirmed'}
    before = {name: client.get(f'/api/builds/{bid}/{name}').json() for name in ARTIFACTS}
    copied = client.post(f'/api/builds/{bid}/versions')
    assert copied.status_code == 201, copied.text
    assert copied.json()['current_version'] == 2 and copied.json()['stage'] == 'prototype'
    assert set(copied.json()['artifacts'].values()) == {'confirmed'}
    after = folder.parent / 'v2'
    for name in ARTIFACTS:
        assert (after / f'docs/{name}.md').read_bytes() == (folder / f'docs/{name}.md').read_bytes()
        assert client.get(f'/api/builds/{bid}/{name}').json() == before[name]
    assert (after / 'spec.json').read_bytes() == (folder / 'spec.json').read_bytes()
    assert sorted(p.name for p in after.glob('background_p*.png')) == sorted(p.name for p in folder.glob('background_p*.png'))
    assert by_node(app, 'versions') == [ok('versions', 'versions')]
    # The copied version compiles once feasibility is recomputed for it.
    from fakes import ready_fixture
    ready_fixture(app, bid, after)
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    assert by_node(app, 'recipe') == [ok('recipe', 'recipe')]


def test_prototype_branch_designs_pages_before_render(blueprint_api, monkeypatch):
    from test_designer import DesignerLLM, designed_flow
    client, app, bid, folder, run_id = designed_flow(blueprint_api, monkeypatch, DesignerLLM())
    assert trace(app, run_id) == ok('prototype', 'prototype', 'view', 'layout', 'designer', 'validate',
                                    'designer', 'validate', 'render', 'publish')


def reference_model(app, monkeypatch, llm, mode):
    monkeypatch.setattr(references, 'decode', lambda images: None)
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: FakeLLM(response=output()) if node == 'reference_extract' else llm)
    files = [('files', ('ref.png', png(), 'image/png'))]
    return accepted(app.state.client.post(f'/api/builds/{app.state.bid}/reference-images', data={'mode': mode}, files=files))


def test_reference_branches_prefill_outline_and_design(outline_api, monkeypatch):
    client, app, bid, sid, folder, llm = outline_api
    app.state.client, app.state.bid = client, bid
    run = reference_model(app, monkeypatch, llm, 'recreate')
    wait(app)
    assert trace(app, run) == ok('reference_extract', 'reference_extract', 'write_reference')
    # A recreate reference is outline proposal input; a style reference is not.
    for mode, observed in (('recreate', True), ('style', False)):
        if mode == 'style':
            run = reference_model(app, monkeypatch, llm, 'style')
            wait(app)
            assert trace(app, run)[1] == 'ok'
        llm.replies.append(json.dumps(proposal()))
        accepted(client.post(f'/api/builds/{bid}/outline/propose'))
        wait(app)
        assert ('Recreate observations' in str(llm.seen[-1].config.system_instruction)) == observed
    confirmed = client.post(f'/api/builds/{bid}/outline/confirm')
    assert confirmed.status_code == 200, confirmed.text
    design = client.get(f'/api/builds/{bid}/design').json()
    assert design['source'] == 'reference' and design['accent'] == STYLE['accent'].upper() and design['issues'] == []
    run = accepted(client.post(f'/api/builds/{bid}/feasibility/check'))
    wait(app)
    assert trace(app, run) == ok('capability_check', 'capability_check', 'assess_capabilities')
    assert client.delete(f'/api/builds/{bid}/reference-images').status_code == 204
    assert by_node(app, 'reference_delete') == [ok('reference_delete', 'reference_delete')]
    # Removing the reference keeps the confirmed Design; only design/prefill replaces it.
    assert client.get(f'/api/builds/{bid}/design').json() == design


def test_research_branch_reaches_context(research_build, monkeypatch):
    client, app, bid, model, search, bq = research_build
    run = accepted(client.post(f'/api/builds/{bid}/research', json={'prompt': 'Player points'}))
    wait(app)
    assert trace(app, run) == ok('research', 'research_discover', 'research_fetch', 'research_select', 'research_intake')
    [source] = client.get(f'/api/builds/{bid}').json()['sources']
    assert source['kind'] == 'research'
    draft = {'title': 'Player points', 'goal': 'Compare player points.', 'audience': None,
             'datasets': [{'source_id': source['id'], 'summary': 'Researched table.'}], 'derived_fields': [],
             'kpis': [{'id': 'total_points', 'name': 'Points', 'description': 'Sum of points.', 'unit': None,
                       'measure': {'field': 'points', 'agg': 'sum'}, 'ratio': None}],
             'thresholds': [], 'glossary': [], 'revision': 1, 'issues': []}
    llm = ContextLLM(replies=[json.dumps(draft)], seen=[])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    run = accepted(client.post(f'/api/builds/{bid}/context'))
    wait(app)
    assert trace(app, run) == ok('context', 'context', 'validate_context')
    assert client.get(f'/api/builds/{bid}/context').json()['issues'] == []
    prompt = str(llm.seen[0].config.system_instruction)
    # The research source reaches the context as its aggregate profile (Data profile).
    assert f"source_id={source['id']}" in prompt and 'points number' in prompt


async def test_revise_and_audit_branches(client, app, build_id, monkeypatch):
    setup = seed_revision(app, build_id, monkeypatch)
    _, _, _, _, service, _ = setup
    fake = FakeLLM(response=response([op('/pages/0/components/0/grid/w', 8), op('/pages/0/components/1/grid/row', 26)]))
    result = await app.state.harness.run('revise', build_id, {
        'config': app.state.settings.get(), 'factory': lambda config: service,
        'comments': [{'component_id': 'p1_revenue', 'text': 'make this bigger'}]}, llm=RevisionModel(delegate=fake))
    assert trace(app, result['run_id']) == ok('revise', 'capability_check', 'assess_capabilities', 'revise',
                                              'validate_revision', 'render')
    from test_audit_style import findings
    audit = await app.state.harness.run('ux_audit', build_id, {'config': app.state.settings.get()},
                                        llm=FakeLLM(response=findings(('p1_revenue', 'high'))))
    assert trace(app, audit['run_id']) == ok('ux_audit', 'ux_audit', 'format_findings')


@pytest.mark.parametrize('action', ['interview', 'plan', 'spec', 'nonsense'])
async def test_unknown_actions_reject_without_a_model(client, app, build_id, monkeypatch, action):
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: pytest.fail('Unknown action constructed a model'))
    with pytest.raises(RunError) as error:
        await app.state.harness.run(action, build_id, {'config': app.state.settings.get()})
    assert error.value.code == 'wrong_stage'
    [(node, status, spans)] = by_node(app, action)
    assert status == 'error' and spans == ['router', 'reject', 'guardrail']
