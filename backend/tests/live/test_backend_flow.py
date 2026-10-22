"""Shared live configuration, evidence, usage and image helpers for the live tests."""
import json
import os
import shutil
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import SecretStr
import pytest
from dss.config import BACKEND_DIR, Config
from dss.data.bigquery import BigQuery
from dss.harness.context import BUDGETS
from dss.main import create_app

RECIPE_SCHEMA = json.loads((BACKEND_DIR.parent / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))


def evidence_dir(task, flow):
    """One folder per run: a rerun never overwrites a failed run's evidence."""
    path = BACKEND_DIR / '.blueprint/qa' / f'task-{task}' / flow / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    path.mkdir(parents=True)
    return path


def validate_recipe(text):
    lines = [json.loads(line) for line in text.rstrip('\n').split('\n')]
    for i, line in enumerate(lines):
        Draft202012Validator({**RECIPE_SCHEMA, '$ref': '#/$defs/op' if i else '#/$defs/header'}).validate(line)
    return lines


def budget(node):
    """A model span's input budget: its own node, else its generation node (context_repair, blueprint_view)."""
    for name in (node, node.removesuffix('_repair'), node.split('_')[0]):
        if name in BUDGETS:
            return BUDGETS[name]
    raise AssertionError(f'no input budget for model span {node}')


def usage(app, run_id):
    """One run's billed tokens, plus each model request's enforced input bound, budget and prompt sections."""
    row = trace(app, run_id)
    requests = []
    for span in json.loads(row['spans_json'] or '[]'):
        if 'sections' not in span:
            continue
        bound = span.get('enforced_input_bound') or span.get('request_tokens') or span['input_tokens_estimate']
        requests.append({'node': span['node'], 'input_bound': bound, 'budget': budget(span['node']),
                         'sections': [f"{s['kind']}:{s['name']}={s['tokens']}" for s in span['sections']],
                         'dropped': span.get('dropped') or {}})
    return {'run_id': run_id, 'node': row['node'], 'model': row['model'], 'status': row['status'],
            'error': row['error'], 'input_tokens': row['input_tokens'], 'output_tokens': row['output_tokens'],
            'latency_ms': row['latency_ms'], 'requests': requests}


def check_usage(run):
    """Every model request fits its node budget and carries no chat history; billed input fits too."""
    for request in run['requests']:
        assert request['input_bound'] <= request['budget'], (run['node'], request)
        assert not any(s.startswith('history:') for s in request['sections']), (run['node'], request['sections'])
    if run['requests']:
        assert run['input_tokens'] <= sum(r['budget'] for r in run['requests']), run
        assert run['output_tokens'] > 0, run


def page_shots(html, spec, folder, prefix='prototype'):
    """Screenshot each `section[data-page]` of a prototype page; returns the PNG paths."""
    from playwright.sync_api import sync_playwright
    paths = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': spec['canvas']['width'], 'height': 900})
            page.set_content(html, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(1500)  # chart animations settle
            for p in spec['pages']:
                path = folder / f"{prefix}_p{p['index']}.png"
                page.locator(f'section[data-page="{p["index"]}"]').screenshot(path=str(path))
                paths.append(path)
        finally:
            browser.close()
    return paths

def trace(app, run_id):
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE run_id=?", (run_id,)).fetchone()
    assert row is not None, run_id
    return dict(row)

def live_app(tmp_path):
    env = Config.from_env()
    assert env.google_api_key.get_secret_value(), 'GOOGLE_API_KEY must be configured'
    project = (os.environ.get('DSS_LIVE_GCP_PROJECT') or env.gcp_project_id).strip()
    assert project, 'GCP_PROJECT_ID must be configured'
    config = env.model_copy(update={'data_dir': tmp_path / 'data', 'db_path': None, 'static_dir': None,
        'access_code': SecretStr(''), 'engine_mode': 'local', 'cloud_service': ''})
    return create_app(config), config, project

REPORT_QUALITY = BACKEND_DIR.parent / 'data/report-quality'
ENGINE_WIDTH = 1380  # widest canvas the engine placed components on without editor zoom (1200 ok, 1440/1560 failed)
MOVE = 'Move this chart to the top of the page, directly under the header.'


def time_designer(monkeypatch, calls):
    """Record each designer model call's wall time and billed tokens (thinking included)."""
    from dss.harness.nodes import designer
    original = designer._generate

    async def timed(model, request, usage):
        call, start = {}, time.monotonic()

        async def record(metadata):
            call.update(input=metadata.prompt_token_count or 0, output=metadata.candidates_token_count or 0,
                        thinking=metadata.thoughts_token_count or 0)
            await usage(metadata)
        try:
            return await original(model, request, record)
        finally:
            calls.append({**call, 'seconds': round(time.monotonic() - start, 1)})
    monkeypatch.setattr(designer, '_generate', timed)


def designed_trace(app, run_id):
    """Designer spans of one run: no fallback, every request within the 12k input / 16k output budgets."""
    spans = json.loads(trace(app, run_id)['spans_json'] or '[]')
    assert not [s for s in spans if s['node'] in ('designer_fallback', 'redesign_failed')], spans
    designs = [s for s in spans if s['node'] == 'designer']
    for span in designs:
        assert (span.get('enforced_input_bound') or span['input_tokens_estimate']) <= BUDGETS['designer'], span
        assert span.get('input_tokens', 0) <= BUDGETS['designer'] and span.get('output_tokens', 0) <= 16000, span
    return designs


@pytest.mark.live
def test_designed_dashboard_sample_csv(tmp_path, monkeypatch):
    """Sample CSV staged flow with the real planner designing every page (no fallback), then one move
    comment that regenerates its page, and a recipe with every page's canvas and background.
    DSS_LIVE_KEEP=1 keeps the BigQuery tables so `dsengine run` can replay the saved recipe."""
    from .test_staged_flow import DATA, OTHER, RATIO_OTHER, SAMPLE_NOTES, Flow, keep, with_ratio
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    app, config, project = live_app(tmp_path)
    assert config.designed_pages
    evidence = evidence_dir('20.5', 'designed')
    tables, flow, folder, calls = [], None, None, []
    facts = {'tables': tables}
    time_designer(monkeypatch, calls)
    facts['designer_calls'] = calls
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'executive', 'mode': 'data', 'title': 'Sales overview'}).json()['id']
        flow, folder, facts['build_id'] = Flow(app, client, bid), config.data_dir / 'builds' / bid / 'v1', bid
        try:
            sources = flow.call('connect', 'post', '/sources/upload', status=201,
                                files=[('files', ('sales.csv', (DATA / 'interview_sales.csv').read_bytes(), 'text/csv'))])['sources']
            tables.extend(s['bq_table'] for s in sources)
            flow.act('context', 'post', '/context', seconds=150, json={'notes': SAMPLE_NOTES})
            edited = flow.call('context', 'put', '/context', json=with_ratio(flow.get('/context')))
            assert edited['issues'] == [], edited['issues']
            ratios = {k['id'] for k in edited['kpis'] if k['ratio']}
            flow.act('outline', 'post', '/context/confirm', seconds=150)
            outline = flow.get('/outline')
            proposed = [q for s in outline['sections'] for q in s['questions'] if ratios & set(q['kpi_refs'])]
            flow.act('outline', 'post', '/outline/other', seconds=150,
                     json={'section_id': outline['sections'][-1]['id'], 'text': OTHER if proposed else RATIO_OTHER})
            outline = flow.get('/outline')
            tick = proposed[0]['id'] if proposed else None
            flow.call('outline', 'put', '/outline/selection', json={'questions': [
                {'id': q['id'], 'selected': q['recommended'] or q['origin'] == 'other' or q['id'] == tick}
                for s in outline['sections'] for q in s['questions']]})
            flow.call('design', 'post', '/outline/confirm')
            design = flow.get('/design')
            if design['page_structure'] != 'per_section':
                design = flow.call('design', 'put', '/design', json={
                    **{k: v for k, v in design.items() if k not in ('revision', 'issues')}, 'page_structure': 'per_section'})
            assert design['page_structure'] == 'per_section' and design['issues'] == [], design
            flow.act('blueprint', 'post', '/design/confirm', seconds=400)
            assessment = flow.get('/feasibility')
            for issue in [i for i in assessment['issues'] if i['resolution'] == 'unresolved']:
                # The ratio question comes with or without a numerator/denominator alternative.
                choice = ({'action': 'accept_alternative', 'alternative_id': issue['alternatives'][0]['id']}
                          if issue['alternatives'] else {'action': 'drop', 'alternative_id': None})
                assessment = flow.call('blueprint', 'post', '/feasibility/decisions', json={
                    'assessment_id': assessment['id'], 'decisions': [{'issue_id': issue['id'], **choice}]})
            assert assessment['state'] == 'ready', assessment

            run = flow.act('prototype', 'post', '/blueprint/accept', seconds=600)
            spec = flow.get('/spec')
            facts['view'] = spec['datasource']['table']
            designs = designed_trace(app, run['run_id'])
            facts['canvas_width'] = spec['canvas']['width']
            # Live 20.5: the Data Studio editor zooms wider canvases to fit and the engine misplaces every component.
            assert spec['canvas']['width'] <= ENGINE_WIDTH, spec['canvas']['width']
            assert len(spec['pages']) >= 2, [p['name'] for p in spec['pages']]
            assert all((p.get('design') or {}).get('source') == 'designer' for p in spec['pages']), \
                [(p['index'], p.get('design') and p['design']['source']) for p in spec['pages']]
            assert {s['page'] for s in designs} == {p['index'] for p in spec['pages']}
            assert all(c['seconds'] <= 120 and c['output'] + c['thinking'] <= 16000 for c in calls), calls
            assert all(c.get('box') for p in spec['pages'] for c in p['components'])
            shots = page_shots(client.get(flow.url + '/prototype').text, spec, evidence, 'prototype')
            REPORT_QUALITY.mkdir(parents=True, exist_ok=True)
            for page, shot in zip(spec['pages'], shots):
                shutil.copyfile(shot, REPORT_QUALITY / f"backend-20.5-p{page['index']}.png")

            charts = ('bar', 'time_series', 'pie', 'scatter', 'table', 'pivot_table', 'geo_map')
            page = next(p for p in spec['pages'] if any(c['type'] in charts for c in p['components']))
            target = [c for c in page['components'] if c['type'] in charts][-1]
            facts['move'] = {'page': page['index'], 'component': target['id'], 'box': target['box']}
            before = len(calls)
            run = flow.act('comment_move', 'post', '/comments', json={'comments': [{'component_id': target['id'], 'text': MOVE}]})
            designed_trace(app, run['run_id'])
            assert len(calls) > before and all(c['seconds'] <= 120 and c['output'] + c['thinking'] <= 16000
                                               for c in calls[before:]), calls
            revised = flow.get('/spec')
            moved = revised['pages'][page['index'] - 1]
            assert moved['design']['source'] == 'revise', moved['design']['source']
            assert [c['id'] for c in moved['components']] == [c['id'] for c in page['components']]
            new_box = next(c['box'] for c in moved['components'] if c['id'] == target['id'])
            facts['move']['new_box'] = new_box
            assert new_box['y'] < target['box']['y'], new_box
            for old, new in zip(spec['pages'], revised['pages']):
                if old['index'] != page['index']:
                    assert new['design'] == old['design'], old['index']
            page_shots(client.get(flow.url + '/prototype').text, revised, evidence, 'revised')

            flow.call('recipe', 'post', '/recipe')
            recipe = validate_recipe((folder / 'recipe.jsonl').read_text(encoding='utf-8'))
            for op in ('set_canvas', 'set_background_image'):
                assert sum(o['op'] == op for o in recipe[1:]) == len(revised['pages']), op
            facts['recipe'] = str(folder / 'recipe.jsonl')
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


def revenue_reference():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': 700})
            page.set_content('''<body style="margin:0;background:#F1F5F9;font-family:Arial;color:#0F172A">
              <h1 style="margin:28px">Regional sales</h1>
              <section style="margin:28px;padding:24px;background:white;border-radius:12px">
              <h2>Revenue by region</h2><svg width="1000" height="450">
              <g fill="#1E40AF"><rect x="100" y="100" width="150" height="300"/>
              <rect x="400" y="200" width="150" height="200"/>
              <rect x="700" y="250" width="150" height="150"/></g>
              <text x="150" y="430">North</text><text x="450" y="430">South</text>
              <text x="750" y="430">West</text></svg></section></body>''')
            return page.screenshot(type='png')
        finally:
            browser.close()
