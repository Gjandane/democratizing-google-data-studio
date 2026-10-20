"""Live interview-to-prototype path through the unmodified API (real Gemini and BigQuery)."""
import json
import os
import struct
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dss.config import BACKEND_DIR, Config
from dss.data.bigquery import BigQuery
from dss.harness.context import BUDGETS
from dss.main import create_app

SAMPLE = Path(__file__).parents[1] / "data/small_sales.csv"
EVIDENCE = BACKEND_DIR / ".blueprint/qa/task-11.8/core"


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
def test_interview_to_prototype(tmp_path):
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
        "request_tokens_vs_estimate": request_counts, "view_rows": len(rows)}, indent=2))
    print(json.dumps({"build_id": build_id, "runs": runs, "plan_nodes": nodes, "view_rows": len(rows),
                      "request_tokens_vs_estimate": request_counts}))


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
