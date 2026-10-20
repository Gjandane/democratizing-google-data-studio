"""Live core and feasibility paths (real Gemini, BigQuery and configured engine dry-run)."""
import json
import os
import struct
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr
from jsonschema import Draft202012Validator

from dss.config import BACKEND_DIR, Config
from dss.data.bigquery import BigQuery
from dss.harness.context import BUDGETS
from dss.main import create_app

SAMPLE = Path(__file__).parents[1] / "data/small_sales.csv"
EVIDENCE = BACKEND_DIR / ".blueprint/qa/task-13.1/core"
RECIPE_SCHEMA = json.loads((BACKEND_DIR.parent / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))


def validate_recipe(text):
    lines = [json.loads(line) for line in text.rstrip('\n').split('\n')]
    for i, line in enumerate(lines):
        Draft202012Validator({**RECIPE_SCHEMA, '$ref': '#/$defs/op' if i else '#/$defs/header'}).validate(line)
    return lines


def wait(app, seconds=300):
    deadline = time.monotonic() + seconds
    while app.state.engine_tasks or app.state.harness.active_builds:
        assert time.monotonic() < deadline, "agent run did not finish in time"
        time.sleep(.25)


def trace(app, run_id):
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE run_id=?", (run_id,)).fetchone()
    assert row is not None, run_id
    return dict(row)


@pytest.mark.live
def test_interview_to_prototype(tmp_path, monkeypatch):
    # Keep the ordinary configured engine invocation; only force its supported no-browser mode.
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    env = Config.from_env()
    assert env.google_api_key.get_secret_value(), "GOOGLE_API_KEY must be configured for this live check"
    # DSS_LIVE_GCP_PROJECT overrides the root .env without editing it.
    project = (os.environ.get("DSS_LIVE_GCP_PROJECT") or env.gcp_project_id).strip()
    assert project, "Set GCP_PROJECT_ID or DSS_LIVE_GCP_PROJECT to an authorized project ID"
    config = env.model_copy(update={"data_dir": tmp_path / "data", "db_path": None, "static_dir": None,
        "access_code": SecretStr(""), "engine_mode": "local", "cloud_service": ""})
    app = create_app(config)
    runs = {}
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"gcp_project_id": project}).status_code == 200
        build = client.post("/api/builds", json={"title": "Live sales", "archetype": "executive", "mode": "data"}).json()
        build_id = build["id"]
        upload = client.post(f"/api/builds/{build_id}/sources/upload",
                             files=[("files", (SAMPLE.name, SAMPLE.read_bytes(), "text/csv"))])
        assert upload.status_code == 201, upload.text

        started = client.post(f"/api/builds/{build_id}/interview/start")
        assert started.status_code == 202, started.text
        runs["interview_start"] = started.json()["run_id"]
        wait(app)
        answer = client.post(f"/api/builds/{build_id}/messages", json={"text":
            "The regional sales director reviews revenue weekly: total revenue, revenue by region and "
            "the daily revenue trend. That is everything; please plan the dashboard."})
        assert answer.status_code == 202, answer.text
        runs["interview_answer"] = answer.json()["run_id"]
        wait(app)
        messages = client.get(f"/api/builds/{build_id}/messages").json()
        assert [m["role"] for m in messages].count("assistant") == 2
        for name in ("interview_start", "interview_answer"):
            assert trace(app, runs[name])["status"] == "ok"

        planned = client.post(f"/api/builds/{build_id}/plan")
        assert planned.status_code == 202, planned.text
        runs["plan"] = planned.json()["run_id"]
        wait(app, 600)
        plan_trace = trace(app, runs["plan"])
        assert plan_trace["status"] == "ok", plan_trace["error"]
        assert client.get(f"/api/builds/{build_id}").json()["stage"] == "prototype"
        nodes = [span["node"] for span in json.loads(plan_trace["spans_json"])]
        assert nodes[:5] == ["router", "capability_check", "assess_capabilities", "plan", "view"]
        assert 1 <= sum(node in ("spec", "spec_repair") for node in nodes) <= 2, nodes
        assert nodes.index("render") > nodes.index("validate")
        # Online requests carry the provider's count of the whole request, apart from the estimates.
        counted = [span for span in json.loads(plan_trace["spans_json"]) if span["node"] in ("plan", "spec", "spec_repair")]
        for span in counted:
            assert isinstance(span["request_tokens"], int) and span["count_calls"] >= 1, span
            assert 0 < span["request_tokens"] <= BUDGETS[span["node"].removesuffix("_repair")], span
            assert isinstance(span["input_tokens_estimate"], int)
        request_counts = {span["node"]: [span["request_tokens"], span["input_tokens_estimate"]] for span in counted}

        folder = config.data_dir / "builds" / build_id / "v1"
        view = yaml.safe_load((folder / "docs/derived-fields.md").read_text(encoding="utf-8").split("---", 2)[1])["view"]
        rows = BigQuery(app.state.settings.get()).aggregate(f"SELECT * FROM `{view}` LIMIT 10")
        assert rows, "view SELECT returned no rows"

        background = client.get(f"/api/builds/{build_id}/files/background_p1.png")
        assert background.status_code == 200
        assert struct.unpack(">II", background.content[16:24])[0] == 1200
        html = client.get(f"/api/builds/{build_id}/prototype").text
        spec = client.get(f"/api/builds/{build_id}/spec").json()

        EVIDENCE.mkdir(parents=True, exist_ok=True)
        compiled = client.post(f'/api/builds/{build_id}/recipe')
        assert compiled.status_code == 200, compiled.text
        recipe = (folder / 'recipe.jsonl').read_text(encoding='utf-8')
        (EVIDENCE / 'recipe.jsonl').write_text(recipe, encoding='utf-8', newline='\n')
        lines = validate_recipe(recipe)
        assert compiled.json()['op_count'] == len(lines) - 1
        executed = client.post(f'/api/builds/{build_id}/run')
        assert executed.status_code == 202, executed.text
        runs['execute'] = executed.json()['run_id']
        wait(app, 600)
        events = (folder / 'events.jsonl').read_text(encoding='utf-8')
        (EVIDENCE / 'events.jsonl').write_text(events, encoding='utf-8', newline='\n')
        outcome = client.get(f'/api/builds/{build_id}').json()
        (EVIDENCE / 'outcome.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
        assert trace(app, runs['execute'])['status'] == 'ok'
        assert outcome['stage'] == 'done', outcome
        validate_recipe((folder / 'recipe.jsonl').read_text(encoding='utf-8'))
        engine_events = [json.loads(line) for line in events.split('\n') if line]
        finished = [event for event in engine_events if event['event'] == 'run_finished']
        assert len(finished) == 1 and finished[0]['status'] == 'ok', finished
        assert finished[0]['report_url'] is None and finished[0]['failed'] == 0
        ops = [event for event in engine_events if event['event'] == 'op_finished']
        assert [op['op_id'] for op in ops] == [op['id'] for op in lines[1:]]
        assert all(op['status'] == 'skipped' for op in ops), ops
        (EVIDENCE / 'spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
        (EVIDENCE / 'traces.json').write_text(json.dumps({name: trace(app, rid) for name, rid in runs.items()}, indent=2), encoding='utf-8')

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": spec["canvas"]["width"], "height": spec["canvas"]["height"]})
            page.set_content(html, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(EVIDENCE / "prototype.png"), full_page=True)
        finally:
            browser.close()
    (EVIDENCE / "background_p1.png").write_bytes(background.content)
    (EVIDENCE / "runs.json").write_text(json.dumps({"build_id": build_id, "runs": runs, "plan_nodes": nodes,
        "plan_tokens": [plan_trace["input_tokens"], plan_trace["output_tokens"]],
        "request_tokens_vs_estimate": request_counts, "view_rows": len(rows),
        "stage": outcome['stage'], "recipe_lines_validated": len(lines), "engine_dry_run": finished[0]}, indent=2))
    print(json.dumps({"build_id": build_id, "runs": runs, "plan_nodes": nodes, "view_rows": len(rows),
                      "request_tokens_vs_estimate": request_counts}))


INTERVIEW_SAMPLE = Path(__file__).parents[1] / "data/interview_sales.csv"
INTERVIEW_TURNS = [
    "The audience is sales executives. Track total revenue, order count, quantity sold and sales trends "
    "using only the uploaded columns.",
    "Total revenue is SUM(revenue). Order count is COUNT(DISTINCT order_id). Quantity sold is SUM(quantity).",
    "Sales trends means SUM(revenue) by month of order_date.",
    "Keep the scope to a single page canvas with series colors #1E40AF and #F59E0B. "
    "That is everything; please plan the dashboard."]

INTERVIEW_RELEASE_TURNS = [
    "The audience is sales executives. Track total revenue, order count, quantity sold and sales trends using only the uploaded columns.",
    "Compare regions and product categories over the full available date range; revenue is SUM(revenue), order count is COUNT(DISTINCT order_id), and quantity sold is SUM(quantity).",
    "Use one executive overview page with KPI scorecards, a revenue trend grouped by order_date at monthly grain, and revenue by region. Use a clean blue theme; proceed with these choices."]


@pytest.mark.live
def test_isolated_release_interview_plan_and_component_accent(tmp_path, monkeypatch):
    """Exact release regression through real extraction, planning and scoped revision."""
    from copy import deepcopy
    from shutil import copy2
    from uuid import uuid4
    from dss.spec import requirements as req
    app, config, project = live_app(tmp_path)
    evidence = BACKEND_DIR / '.blueprint/qa/task-14.2/interview' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    evidence.mkdir(parents=True)
    turns, runs = [], []
    folder = None
    # Observe the real validator; save failed as well as successful model output.
    from dss.harness.nodes import validate as validator
    original_validate = validator.validate_spec
    attempts = []
    def observed_validate(value, **kwargs):
        attempts.append(value)
        (evidence / f'candidate-{len(attempts)}.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
        errors = original_validate(value, **kwargs)
        (evidence / f'candidate-{len(attempts)}-errors.json').write_text(json.dumps(errors, indent=2), encoding='utf-8')
        return errors
    monkeypatch.setattr(validator, 'validate_spec', observed_validate)
    original_coverage = req.coverage_errors
    def observed_coverage(*args, **kwargs):
        try:
            errors = original_coverage(*args, **kwargs)
        except ValueError as error:
            (evidence / f'candidate-{len(attempts)}-coverage-error.txt').write_text(str(error), encoding='utf-8')
            raise
        (evidence / f'candidate-{len(attempts)}-coverage.json').write_text(json.dumps(errors, indent=2), encoding='utf-8')
        return errors
    monkeypatch.setattr(req, 'coverage_errors', observed_coverage)

    def capture(client, bid, label):
        spec = client.get(f'/api/builds/{bid}/spec').json()
        html = client.get(f'/api/builds/{bid}/prototype').text
        (evidence / f'{label}-spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
        (evidence / f'{label}-prototype.html').write_text(html, encoding='utf-8')
        if (folder / 'requirements.json').is_file():
            copy2(folder / 'requirements.json', evidence / f'{label}-requirements.json')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': spec['canvas']['width'], 'height': spec['canvas']['height']})
                page.set_content(html, wait_until='networkidle')
                page.screenshot(path=str(evidence / f'{label}-prototype.png'), full_page=True)
            finally:
                browser.close()
        return spec

    try:
        with TestClient(app) as client:
            bid = live_build(client, project, INTERVIEW_SAMPLE.read_bytes())
            folder = config.data_dir / 'builds' / bid / 'v1'
            started = client.post(f'/api/builds/{bid}/interview/start')
            assert started.status_code == 202, started.text
            wait(app)
            runs.append(trace(app, started.json()['run_id']))
            assert runs[-1]['status'] == 'ok', runs[-1]['error']
            for text in INTERVIEW_RELEASE_TURNS:
                response = client.post(f'/api/builds/{bid}/messages', json={'text': text})
                assert response.status_code == 202, response.text
                wait(app)
                runs.append(trace(app, response.json()['run_id']))
                assessment = client.get(f'/api/builds/{bid}/feasibility').json()
                turns.append({'text': text, 'trace': runs[-1], 'assessment': assessment,
                              'messages': client.get(f'/api/builds/{bid}/messages').json()})
                assert runs[-1]['status'] == 'ok', runs[-1]['error']
            assert assessment['state'] == 'ready', assessment
            assert client.get(f'/api/builds/{bid}').json()['ready_for_plan']
            ledger = req.load(folder)
            mappings = {(m.field, m.aggregation) for r in ledger.requirements for m in r.mappings}
            assert {('revenue', 'sum'), ('order_id', 'count_distinct'), ('quantity', 'sum')} <= mappings, mappings
            assert any(m.date_grain == 'month' and m.field == 'revenue' and
                       any(n.fields.get('date_field') == 'order_date' for n in r.needs)
                       for r in ledger.requirements for m in r.mappings), ledger
            response = client.post(f'/api/builds/{bid}/plan')
            assert response.status_code == 202, response.text
            wait(app, 600)
            runs.append(trace(app, response.json()['run_id']))
            assert runs[-1]['status'] == 'ok', runs[-1]['error']
            assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
            before = capture(client, bid, 'before')
            charts = [c for c in before['pages'][0]['components'] if c['type'] in ('bar', 'time_series')
                      and {'field': 'revenue', 'agg': 'sum'} in c['metrics']]
            assert charts, before
            target = charts[0]
            def blue(color):
                red, green, channel = (int(color[i:i+2], 16) for i in (1, 3, 5))
                return channel > red and channel > green
            assert before['theme']['palette'] and any(blue(color) for color in before['theme']['palette']), before['theme']
            comment = 'Use a dark blue accent for this component; preserve its position and data.'
            response = client.post(f'/api/builds/{bid}/comments', json={'comments': [{'component_id': target['id'], 'text': comment}]})
            assert response.status_code == 202, response.text
            wait(app)
            runs.append(trace(app, response.json()['run_id']))
            assessment = client.get(f'/api/builds/{bid}/feasibility').json()
            turns.append({'text': comment, 'trace': runs[-1], 'assessment': assessment})
            assert runs[-1]['status'] == 'ok', runs[-1]['error']
            assert assessment['state'] == 'ready' and assessment['pending_comments'] is None, assessment
            after = capture(client, bid, 'after')
            expected = deepcopy(before)
            expected['spec_version'] = after['spec_version']
            next(c for c in expected['pages'][0]['components'] if c['id'] == target['id'])['colors'] = ['#172554']
            assert after == expected
            assert after['spec_version'] > before['spec_version']
            compiled = client.post(f'/api/builds/{bid}/recipe')
            assert compiled.status_code == 200, compiled.text
            recipe = validate_recipe((folder / 'recipe.jsonl').read_text(encoding='utf-8'))
            assert any(op['op'] == 'set_style' and op['component_id'] == target['id'] and op['style']['colors'] == ['#172554'] for op in recipe[1:])
    finally:
        (evidence / 'turns.json').write_text(json.dumps(turns, indent=2), encoding='utf-8')
        (evidence / 'traces.json').write_text(json.dumps(runs, indent=2), encoding='utf-8')
        with app.state.db.connect() as conn:
            events = [{'kind': r[0], 'payload': json.loads(r[1])} for r in conn.execute('SELECT kind,payload_json FROM events ORDER BY rowid')]
        (evidence / 'api-events.json').write_text(json.dumps(events, indent=2), encoding='utf-8')
        if folder is not None and folder.exists():
            # Explicit metadata/artifact allowlist: no database, settings or credentials.
            for name in ('requirements.json', 'spec.json', 'prototype.html', 'background_p1.png', 'recipe.jsonl'):
                if (folder / name).is_file():
                    copy2(folder / name, evidence / name)
            if (folder / 'docs').is_dir():
                (evidence / 'docs').mkdir(exist_ok=True)
                for path in (folder / 'docs').glob('*.md'):
                    copy2(path, evidence / 'docs' / path.name)


@pytest.mark.live
def test_isolated_three_turn_interview_feasibility(tmp_path):
    """Release 2.2 wording with the real extractor: no injected ledger or spec."""
    from dss.spec import requirements as req
    app, config, project = live_app(tmp_path)
    # One folder per run: a later pass never overwrites a failed run's evidence.
    evidence = BACKEND_DIR / ".blueprint/qa/task-14.1/interview" / time.strftime("%Y%m%d-%H%M%S")
    evidence.mkdir(parents=True, exist_ok=True)
    turns = []
    folder = None
    try:
        with TestClient(app) as client:
            bid = live_build(client, project, INTERVIEW_SAMPLE.read_bytes())
            folder = config.data_dir / 'builds' / bid / 'v1'
            started = client.post(f'/api/builds/{bid}/interview/start')
            assert started.status_code == 202, started.text
            wait(app)
            assert trace(app, started.json()['run_id'])['status'] == 'ok'
            for i, text in enumerate(INTERVIEW_TURNS):
                response = client.post(f'/api/builds/{bid}/messages', json={'text': text})
                assert response.status_code == 202, response.text
                wait(app)
                run = trace(app, response.json()['run_id'])
                assessment = client.get(f'/api/builds/{bid}/feasibility').json()
                build = client.get(f'/api/builds/{bid}').json()
                messages = client.get(f'/api/builds/{bid}/messages').json()
                turns.append({'text': text, 'trace': run, 'assessment': assessment, 'ready_for_plan': build['ready_for_plan'],
                              'reply': messages[-1]['text'] if messages[-1]['role'] == 'assistant' else None})
                # Every valid conversational turn finishes with one trace, one extraction and a reply.
                assert run['status'] == 'ok', run['error']
                assert [s['node'] for s in json.loads(run['spans_json'])].count('capability_check') == 1
                assert [m['role'] for m in messages].count('assistant') == i + 2
                assert not [x for x in assessment['issues'] if 'audience' in x['requirement'].lower()], assessment
                unresolved = [x for x in assessment['issues'] if x['resolution'] == 'unresolved']
                if unresolved:
                    assert assessment['state'] == 'blocked' and not build['ready_for_plan']
                if i == 0:
                    # Order count and the trend are incomplete: readiness stays false.
                    assert unresolved and not build['ready_for_plan'], assessment
            assert assessment['state'] == 'ready', assessment
            assert build['ready_for_plan'] is True
            ledger = req.load(folder)
            first = [r for r in ledger.requirements if r.source.text == INTERVIEW_TURNS[0]]
            assert any(req.audience_requirement(r, ledger) for r in first), ledger
            mappings = {(m.field, m.aggregation) for r in ledger.requirements for m in r.mappings}
            assert {('revenue', 'sum'), ('order_id', 'count_distinct'), ('quantity', 'sum')} <= mappings, mappings
            # The monthly order_date trend keeps both its grain and its date binding.
            assert any(m.date_grain == 'month' and m.field == 'revenue' and any(n.fields.get('date_field') == 'order_date' for n in r.needs)
                       for r in ledger.requirements for m in r.mappings), ledger
    finally:
        (evidence / 'turns.json').write_text(json.dumps(turns, indent=2), encoding='utf-8')
        if folder is not None and (folder / 'requirements.json').is_file():
            (evidence / 'requirements.json').write_text((folder / 'requirements.json').read_text(encoding='utf-8'), encoding='utf-8')


def live_app(tmp_path):
    env = Config.from_env()
    assert env.google_api_key.get_secret_value(), 'GOOGLE_API_KEY must be configured'
    project = (os.environ.get('DSS_LIVE_GCP_PROJECT') or env.gcp_project_id).strip()
    assert project, 'GCP_PROJECT_ID must be configured'
    config = env.model_copy(update={'data_dir': tmp_path / 'data', 'db_path': None, 'static_dir': None,
        'access_code': SecretStr(''), 'engine_mode': 'local', 'cloud_service': ''})
    return create_app(config), config, project


def live_build(client, project, csv):
    assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
    response = client.post('/api/builds', json={'title': 'Live feasibility', 'archetype': 'executive', 'mode': 'data'})
    assert response.status_code == 201, response.text
    bid = response.json()['id']
    response = client.post(f'/api/builds/{bid}/sources/upload', files=[('files', ('sales.csv', csv, 'text/csv'))])
    assert response.status_code == 201, response.text
    return bid


@pytest.mark.live
def test_moving_gps_refused_before_view(tmp_path):
    from dss.spec import requirements as req
    app, config, project = live_app(tmp_path)
    with TestClient(app) as client:
        bid = live_build(client, project, SAMPLE.read_bytes())
        response = client.post(f'/api/builds/{bid}/messages', json={'text':
            'The operations director needs animated GPS points moving continuously along vehicle routes. '
            'Temporal point playback is required, not a static aggregate map.'})
        # Start the ordinary interview before sending its answer.
        assert response.status_code == 409
        assert client.post(f'/api/builds/{bid}/interview/start').status_code == 202
        wait(app)
        response = client.post(f'/api/builds/{bid}/messages', json={'text':
            'The operations director needs animated GPS points moving continuously along vehicle routes. '
            'Temporal point playback is required, not a static aggregate map.'})
        assert response.status_code == 202, response.text
        wait(app)
        assessment = client.get(f'/api/builds/{bid}/feasibility').json()
        assert assessment['state'] == 'blocked', assessment
        assert any(i['status'] == 'unsupported_app' for i in assessment['issues']), assessment
        build = client.get(f'/api/builds/{bid}').json()
        assert not build['ready_for_plan'] and build['stage'] == 'interview'
        folder = config.data_dir / 'builds' / bid / 'v1'
        ledger = req.load(folder)
        assert any(n.capability == 'animation.temporal_playback' for r in ledger.requirements for n in r.needs)
        response = client.post(f'/api/builds/{bid}/plan')
        assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
        assert not (folder / 'spec.json').exists() and not (folder / 'recipe.jsonl').exists()
        with app.state.db.connect() as conn:
            spans = [s for row in conn.execute('SELECT spans_json FROM traces WHERE build_id=?', (bid,))
                     for s in json.loads(row[0])]
        assert not any(s['node'] == 'view' for s in spans)
    evidence = EVIDENCE.parent / 'gps'
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'assessment.json').write_text(json.dumps(assessment, indent=2), encoding='utf-8')
    (evidence / 'requirements.json').write_text(ledger.model_dump_json(indent=2), encoding='utf-8')


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


@pytest.mark.live
def test_image_revenue_mapping_clarified_to_real_prototype(tmp_path):
    from dss.spec import requirements as req
    app, config, project = live_app(tmp_path)
    image = revenue_reference()
    csv = (b'date,region,gross_sales,net_sales\n2026-01-01,North,100,80\n'
           b'2026-01-01,South,120,90\n2026-01-02,West,150,110\n2026-01-02,North,80,60\n')
    evidence = EVIDENCE.parent / 'image-mapping'
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'reference.png').write_bytes(image)
    with TestClient(app) as client:
        bid = live_build(client, project, csv)
        response = client.post(f'/api/builds/{bid}/reference-images', data={'mode': 'recreate'},
            files=[('files', ('revenue.png', image, 'image/png'))])
        assert response.status_code == 202, response.text
        wait(app)
        assert trace(app, response.json()['run_id'])['status'] == 'ok'
        assert client.post(f'/api/builds/{bid}/feasibility/check').status_code == 202
        wait(app)
        ambiguous = client.get(f'/api/builds/{bid}/feasibility').json()
        assert ambiguous['state'] == 'blocked' and any(i['status'] == 'needs_clarification' for i in ambiguous['issues']), ambiguous
        assert client.post(f'/api/builds/{bid}/interview/start').status_code == 202
        wait(app)
        assert client.post(f'/api/builds/{bid}/plan').json()['error']['code'] == 'feasibility_blocked'
        response = client.post(f'/api/builds/{bid}/messages', json={'text':
            'For the regional sales director, Revenue means net_sales, using sum in USD. '
            'Use region as the bar chart dimension. Recreate the reference with real charts using this '
            'definition. There are no other requirements; please plan it.'})
        assert response.status_code == 202, response.text
        wait(app)
        clarified = client.get(f'/api/builds/{bid}/feasibility').json()
        assert clarified['state'] == 'ready', clarified
        response = client.post(f'/api/builds/{bid}/plan')
        assert response.status_code == 202, response.text
        wait(app, 600)
        result = trace(app, response.json()['run_id'])
        assert result['status'] == 'ok', result['error']
        assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
        folder = config.data_dir / 'builds' / bid / 'v1'
        ledger = req.load(folder)
        image_requirements = [r for r in ledger.requirements if r.source.kind == 'image']
        assert image_requirements and any(m.field == 'net_sales' and m.aggregation == 'sum'
                                          for r in image_requirements for m in r.mappings)
        assert all(m.field != 'gross_sales' for r in image_requirements for m in r.mappings)
        spec = client.get(f'/api/builds/{bid}/spec').json()
        charts = [c for p in spec['pages'] for c in p['components'] if c['type'] == 'bar']
        assert any('region' in c['dimensions'] and {'field': 'net_sales', 'agg': 'sum'} in c['metrics'] for c in charts)
        compiled = client.post(f'/api/builds/{bid}/recipe')
        assert compiled.status_code == 200, compiled.text
        recipe = (folder / 'recipe.jsonl').read_text(encoding='utf-8')
        validate_recipe(recipe)
        assert 'reference_' not in recipe and '"add_chart"' in recipe
        reference = client.get(f'/api/builds/{bid}/reference-images').json()
        background = (folder / 'background_p1.png').read_bytes()
        assert background != image
        assert all(c.get('image_path') != reference['images'][0]['file'] for p in spec['pages'] for c in p['components'])
        html = client.get(f'/api/builds/{bid}/prototype').text
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': spec['canvas']['width'], 'height': spec['canvas']['height']})
                page.set_content(html, wait_until='networkidle')
                page.screenshot(path=str(evidence / 'prototype.png'), full_page=True)
            finally:
                browser.close()
        (evidence / 'requirements.json').write_text(ledger.model_dump_json(indent=2), encoding='utf-8')
        (evidence / 'assessments.json').write_text(json.dumps({'ambiguous': ambiguous, 'clarified': clarified}, indent=2), encoding='utf-8')
