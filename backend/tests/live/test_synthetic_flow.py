"""Live typed intake and screenshot-only synthetic dashboard flow through the real API."""
import os
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dss.config import Config
from dss.data.bigquery import BigQuery
from dss.main import create_app


def column(name, kind, generator, nullable=0):
    return {"name": name, "type": kind, "nullable_fraction": nullable, "generator": generator}


# One all-null column per type, a string ID column with leading zeros, and all-empty records.
MIXED = {"schema_version": 1, "row_count": 300, "seed": 11, "columns": [
    column("code", "string", {"kind": "choice", "values": ["001", "010"]}, nullable=.4),
    column("units", "integer", {"kind": "integer", "min": 1, "max": 9}, nullable=.4),
    column("empty_amount", "number", {"kind": "decimal", "min": 0, "max": 5, "decimals": 2}, nullable=1),
    column("empty_day", "date", {"kind": "date", "start": "2026-01-01", "end": "2026-12-31"}, nullable=1),
    column("empty_flag", "boolean", {"kind": "boolean", "true_probability": .5}, nullable=1)]}
# A single column whose every value is null: csv.writer writes each record as `""`.
SINGLE = {"schema_version": 1, "row_count": 40, "seed": 2,
          "columns": [column("only", "integer", {"kind": "integer", "min": 0, "max": 1}, nullable=1)]}


def wait(app, seconds=300):
    deadline = time.monotonic() + seconds
    while app.state.engine_tasks or app.state.harness.active_builds:
        assert time.monotonic() < deadline, "generation did not finish in time"
        time.sleep(.25)


@pytest.mark.live
def test_synthetic_typed_load(tmp_path):
    env = Config.from_env()
    project = (os.environ.get("DSS_LIVE_GCP_PROJECT") or env.gcp_project_id).strip()
    assert project, "Set GCP_PROJECT_ID or DSS_LIVE_GCP_PROJECT to an authorized project ID"
    config = env.model_copy(update={"data_dir": tmp_path / "data", "db_path": None, "static_dir": None,
        "access_code": SecretStr(""), "engine_mode": "local", "cloud_service": ""})
    app = create_app(config)
    tables = []
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"gcp_project_id": project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        try:
            for spec, types in ((MIXED, ["STRING", "INTEGER", "NUMERIC", "DATE", "BOOLEAN"]), (SINGLE, ["INTEGER"])):
                build_id = client.post("/api/builds", json={"archetype": "executive", "mode": "data"}).json()["id"]
                response = client.post(f"/api/builds/{build_id}/synthetic-data",
                                       json={"generation_key": "live_1", "proposal_id": None, "spec": spec})
                assert response.status_code == 202, response.text
                wait(app)
                status = client.get(f"/api/builds/{build_id}/synthetic-data/jobs/live_1").json()
                assert status["state"] == "succeeded", status
                [source] = client.get(f"/api/builds/{build_id}").json()["sources"]
                tables.append(source["bq_table"])
                assert source["kind"] == "synthetic" and source["row_count"] == spec["row_count"]
                table = service.client.get_table(source["bq_table"])
                assert [(f.name, f.field_type) for f in table.schema] == list(zip([c["name"] for c in spec["columns"]], types))
                assert table.num_rows == spec["row_count"]
                lines = client.get(f"/api/builds/{build_id}/synthetic-data/{source['id']}/csv").text.split("\n")[1:-1]
                assert len(lines) == spec["row_count"]
                names = [c["name"] for c in spec["columns"]]
                every_null = " AND ".join(f"`{n}` IS NULL" for n in names)
                [row] = service.client.query(
                    f"SELECT COUNT(*) AS total, COUNTIF({every_null}) AS empty_rows"
                    + (", COUNTIF(code = '001') AS ids, COUNTIF(empty_amount IS NOT NULL OR empty_day IS NOT NULL "
                       "OR empty_flag IS NOT NULL) AS filled" if spec is MIXED else "")
                    + f" FROM `{source['bq_table']}`").result(timeout=120)
                assert row["total"] == spec["row_count"]
                expected_empty = sum(line in (",,,,", '""') for line in lines)
                assert row["empty_rows"] == expected_empty > 0
                if spec is MIXED:
                    assert row["ids"] == sum(line.startswith("001,") for line in lines) > 0 and row["filled"] == 0
        finally:
            for table in tables:
                service.client.delete_table(table, not_found_ok=True)


@pytest.mark.live
def test_screenshot_only_to_labelled_prototype_and_recipe(tmp_path):
    import csv
    import io
    import json
    from pathlib import Path
    import yaml
    from playwright.sync_api import sync_playwright
    from .test_backend_flow import live_app, revenue_reference, trace
    from dss.config import BACKEND_DIR
    from dss.spec.models import SYNTHETIC_LABEL_ID, SYNTHETIC_LABEL

    app, config, project = live_app(tmp_path)
    evidence = BACKEND_DIR / '.blueprint/qa/task-12.5'
    evidence.mkdir(parents=True, exist_ok=True)
    image = revenue_reference()
    (evidence / 'reference.png').write_bytes(image)
    tables = []
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'title': 'Synthetic regional sales', 'archetype': 'executive', 'mode': 'data'}).json()['id']
        url = f'/api/builds/{bid}'
        folder = config.data_dir / 'builds' / bid / 'v1'
        def action(response, seconds=300):
            assert response.status_code == 202, response.text
            wait(app, seconds)
            result = trace(app, response.json()['run_id'])
            assert result['status'] == 'ok', result['error']
        try:
            assert client.get(url).json()['sources'] == []
            action(client.post(url + '/reference-images', data={'mode': 'recreate'},
                files=[('files', ('sales.png', image, 'image/png'))]))
            reference = client.get(url + '/reference-images').json()
            action(client.post(url + '/synthetic-data/proposal', json={'reference_set_id': reference['id']}))
            proposal = client.get(url + '/synthetic-data/proposal').json()
            assert proposal and proposal['assumptions']
            assert client.get(url).json()['sources'] == []
            spec = {**proposal['spec'], 'row_count': 1000, 'seed': 42}
            action(client.post(url + '/synthetic-data', json={'generation_key': 'screenshot_1000',
                   'proposal_id': proposal['id'], 'spec': spec}))
            source, = client.get(url).json()['sources']
            tables.append(source['bq_table'])
            assert source['kind'] == 'synthetic' and source['row_count'] == 1000
            download = client.get(url + f"/synthetic-data/{source['id']}/csv")
            assert download.status_code == 200
            rows = list(csv.reader(io.StringIO(download.text)))
            assert len(rows) == 1001 and rows[0] == [c['name'] for c in spec['columns']]
            types = {'integer': 'INTEGER', 'number': 'NUMERIC', 'string': 'STRING', 'boolean': 'BOOLEAN', 'date': 'DATE'}
            table = service.client.get_table(source['bq_table'])
            assert [f.field_type for f in table.schema] == [types[c['type']] for c in spec['columns']]
            action(client.post(url + '/interview/start'))
            # Explicitly confirm the proposed definitions without assuming provider-chosen names.
            action(client.post(url + '/messages', json={'text':
                'For the regional sales director, use the generated sample schema and its assumed '
                'definitions exactly as proposed. Revenue is the sum of the proposed revenue metric in USD; '
                'use the proposed region field as its bar chart dimension. Recreate Revenue by region '
                'as a static bar chart matching the reference. This is invented sample data, not '
                'recovered original values. That is everything; please plan it. '
                'Accepted schema: ' + json.dumps(spec)}))
            ready = client.get(url + '/feasibility').json()
            assert ready['state'] == 'ready', ready
            action(client.post(url + '/plan'), 600)
            assert client.get(url).json()['stage'] == 'prototype'
            dashboard = client.get(url + '/spec').json()
            assert dashboard['datasource']['synthetic']
            assert any(d['id'] == SYNTHETIC_LABEL_ID and d['text'] == SYNTHETIC_LABEL
                       for d in dashboard['pages'][0]['decorations'])
            html = client.get(url + '/prototype').text
            assert SYNTHETIC_LABEL in html
            compiled = client.post(url + '/recipe')
            assert compiled.status_code == 200, compiled.text
            assert SYNTHETIC_LABEL in (folder / 'recipe.jsonl').read_text(encoding='utf-8')
            derived = yaml.safe_load((folder / 'docs/derived-fields.md').read_text(encoding='utf-8').split('---', 2)[1])
            tables.append(derived['view'])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1200, 'height': dashboard['canvas']['height']})
                    page.set_content(html, wait_until='networkidle')
                    assert page.locator(f'[data-cid="{SYNTHETIC_LABEL_ID}"]').is_visible()
                    page.screenshot(path=str(evidence / 'prototype.png'), full_page=True)
                finally:
                    browser.close()
            (evidence / 'background_p1.png').write_bytes((folder / 'background_p1.png').read_bytes())
            (evidence / 'proposal.json').write_text(json.dumps(proposal, indent=2), encoding='utf-8')
            (evidence / 'spec.json').write_text(json.dumps(dashboard, indent=2), encoding='utf-8')
            (evidence / 'recipe.jsonl').write_bytes((folder / 'recipe.jsonl').read_bytes())
            cid = dashboard['pages'][0]['components'][0]['id']
            # Synthetic data resolves missing rows, never unsupported GPS animation.
            response = client.post(url + '/comments', json={'comments': [{'component_id': cid, 'text':
                'Replace this with animated GPS points moving continuously along vehicle routes. '
                'Temporal point playback is required, not a static aggregate map.'}]})
            assert response.status_code == 202, response.text
            wait(app)
            blocked = client.get(url + '/feasibility').json()
            assert blocked['state'] == 'blocked', blocked
            assert any(i['status'] == 'unsupported_app' for i in blocked['issues']), blocked
            assert client.post(url + '/plan').status_code == 409
            (evidence / 'gps-assessment.json').write_text(json.dumps(blocked, indent=2), encoding='utf-8')
        finally:
            # Include a candidate view even if a later assertion failed.
            path = folder / 'docs/derived-fields.md'
            if path.exists():
                derived = yaml.safe_load(path.read_text(encoding='utf-8').split('---', 2)[1])
                if derived.get('view') not in tables:
                    tables.append(derived['view'])
            for table in tables:
                service.client.delete_table(table, not_found_ok=True)
