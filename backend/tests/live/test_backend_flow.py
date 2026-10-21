"""Shared live configuration, evidence, usage and image helpers for the live tests."""
import json
import os
import time
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import SecretStr
from dss.config import BACKEND_DIR, Config
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
