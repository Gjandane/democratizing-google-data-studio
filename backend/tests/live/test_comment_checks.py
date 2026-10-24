"""Task 24.3 live check: a style-mode build keeps taking comments as its ledger grows."""
import json
import os

from fastapi.testclient import TestClient
import pytest

from dss.config import BACKEND_DIR
from dss.data.bigquery import BigQuery
from dss.harness.context import BUDGETS
from dss.spec import requirements as req
from .test_backend_flow import MOVE, evidence_dir, live_app, trace

REFERENCE = BACKEND_DIR.parent / 'data/references/electricity-access.jpg'
CHARTS = ('bar', 'time_series', 'pie', 'scatter', 'table', 'pivot_table', 'geo_map', 'area')


def comments(spec):
    """Eight app-supported comments (title, move, series colors) on the prototype's charts. Live 24.3:
    a vague "make the header taller" is a correct `unknown` and a title font size `unsupported_app`."""
    charts = [c for p in spec['pages'] for c in p['components'] if c['type'] in CHARTS]
    assert charts, spec['pages']
    a, b, c = [x['id'] for x in (charts * 3)[:3]]
    colored = [x['id'] for x in charts if x['type'] in ('bar', 'time_series', 'pie', 'area')] or [a]
    d, e = (colored * 2)[:2]
    return [(a, "Rename this chart to 'Revenue by region at a glance'."),
            (d, "Color this chart's series dark blue (#1E3A8A)."),
            (a, MOVE),
            (c, "Rename this chart to 'Monthly net revenue trend'."),
            (b, "Rename this chart to 'Orders by category'."),
            (e, "Color this chart's series teal (#0F766E)."),
            (b, MOVE),
            (d, "Color this chart's series amber (#B45309).")]


@pytest.mark.live
def test_style_build_takes_eight_comments_within_the_comment_check_budget(tmp_path, monkeypatch):
    from .test_staged_flow import DATA, SAMPLE_NOTES, Flow, keep
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    app, config, project = live_app(tmp_path)
    evidence = evidence_dir('24.3', 'comments')
    tables, flow, folder, checks = [], None, None, []
    facts = {'tables': tables, 'capability_checks': checks}
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'executive', 'mode': 'data', 'title': 'Sales overview'}).json()['id']
        flow, folder, facts['build_id'] = Flow(app, client, bid), config.data_dir / 'builds' / bid / 'v1', bid
        try:
            sources = flow.call('connect', 'post', '/sources/upload', status=201,
                                files=[('files', ('sales.csv', (DATA / 'interview_sales.csv').read_bytes(), 'text/csv'))])['sources']
            tables.extend(s['bq_table'] for s in sources)
            flow.act('reference', 'post', '/reference-images', seconds=180,
                     data={'mode': 'style', 'instructions': 'Use the colors, font and soft white panels of this dashboard.'},
                     files=[('files', ('electricity-access.jpg', REFERENCE.read_bytes(), 'image/jpeg'))])
            flow.act('context', 'post', '/context', seconds=150, json={'notes': SAMPLE_NOTES})
            flow.act('outline', 'post', '/context/confirm', seconds=150)
            outline = flow.get('/outline')
            flow.call('outline', 'put', '/outline/selection', json={'questions': [
                {'id': q['id'], 'selected': q['recommended']} for s in outline['sections'] for q in s['questions']]})
            flow.call('design', 'post', '/outline/confirm')
            flow.act('blueprint', 'post', '/design/confirm', seconds=400)
            assessment = flow.get('/feasibility')
            if any(i['id'].startswith('bp_intent_') for i in assessment['issues']):
                # The style instructions are new intent: one explicit check extracts them.
                flow.act('feasibility', 'post', '/feasibility/check', seconds=150)
                assessment = flow.get('/feasibility')
            for issue in [i for i in assessment['issues'] if i['resolution'] == 'unresolved']:
                choice = ({'action': 'accept_alternative', 'alternative_id': issue['alternatives'][0]['id']}
                          if issue['alternatives'] else {'action': 'drop', 'alternative_id': None})
                assessment = flow.call('blueprint', 'post', '/feasibility/decisions', json={
                    'assessment_id': assessment['id'], 'decisions': [{'issue_id': issue['id'], **choice}]})
            assert assessment['state'] == 'ready', assessment
            flow.act('prototype', 'post', '/blueprint/accept', seconds=600)
            spec = flow.get('/spec')
            facts['view'] = spec['datasource']['table']
            for n, (target, text) in enumerate(comments(spec), 1):
                run = flow.act(f'comment_{n}', 'post', '/comments', seconds=400,
                               json={'comments': [{'component_id': target, 'text': text}]})
                spans = json.loads(trace(app, run['run_id'])['spans_json'] or '[]')
                [span] = [s for s in spans if s['node'] == 'capability_check']
                checks.append({'comment': n, 'target': target, **{k: span.get(k) for k in (
                    'request_tokens', 'input_tokens_estimate', 'ledger_rows_sent', 'ledger_rows_kept', 'skipped')},
                    'sections': {s['name']: s['tokens'] for s in span.get('sections', [])}})
                ledger = req.load(folder)
                checks[-1].update(requirements=len(ledger.requirements), state=ledger.assessment.state,
                                  revised=flow.get('/spec')['spec_version'])
                assert ledger.scope_error is None, (n, ledger.scope_error)
                # Taken, not merely unrefused: a blocked batch would be abandoned and the ledger not grow.
                assert ledger.assessment.state == 'ready' and ledger.pending_comments is None, checks[-1]
                assert span.get('skipped') or span['request_tokens'] < BUDGETS['capability_check'] == 24000, checks[-1]
            facts['requirements'] = len(req.load(folder).requirements)
            assert len(checks) == 8 and not any(c['skipped'] for c in checks), checks
            assert checks[-1]['requirements'] > checks[0]['requirements'], checks  # the ledger grew
        finally:
            try:
                keep(evidence, flow, folder, facts)
            finally:
                if os.environ.get('DSS_LIVE_KEEP') != '1':
                    response = client.get(flow.url + '/blueprint') if flow else None
                    drafted = response.json() if response is not None and response.status_code == 200 else None
                    for table in tables + [facts.get('view'), (drafted or {}).get('view_table')]:
                        if table:
                            service.client.delete_table(table, not_found_ok=True)
