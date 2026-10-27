"""Contract shapes for endpoints implemented through phase 4; later phases add theirs."""
import json
import pytest
from pathlib import Path
from test_thin_slice import thin, load
from test_execute import settle
from test_recipe_contract import agent_client, no_engine, spec

FIXTURES = Path(__file__).resolve().parents[2] / "contracts/fixtures/api"
NULLABLE = {"spec_version": int, "report_url": str, "node": str, "model": str, "error": str, "build_id": str, "agent_last_seen": str, "notes": str}


def shape(actual, expected, field=""):
    if field in NULLABLE and not isinstance(expected, dict):
        assert actual is None or type(actual) is NULLABLE[field]
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key in expected:
            shape(actual[key], expected[key], key)
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        for item in actual:
            shape(item, expected[0])
    else:
        assert type(actual) is type(expected)


def check(response, fixture, status=200):
    assert response.status_code == status, response.text
    shape(response.json(), json.loads((FIXTURES / fixture).read_text()))


def test_design_pages_contract_and_legacy_versions(client, app, build_id):
    from dss.spec.models import Design
    from dss.spec.publication import design_artifacts
    from dss.harness.nodes import reference_brief as rb
    from test_render import three_pages
    base = f'/api/builds/{build_id}'
    assert client.get(base + '/design-pages').json() == {'version': 1, 'spec_version': None, 'pages': [], 'review': None}
    assert client.get('/api/builds/missing/design-pages').status_code == 404
    folder = app.state.settings.get().data_dir / 'builds' / build_id / 'v2'
    folder.mkdir(parents=True)
    spec = three_pages()
    spec.spec_version = 5
    spec.pages = spec.pages[:2]
    spec.pages[0].design = Design(html='<p>Design</p>', source='designer', model='gemini-3.8-flash')
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET current_version=2 WHERE id=?', (build_id,))
    legacy = client.get(base + '/design-pages').json()
    assert legacy == {'version': 2, 'spec_version': 5, 'review': None, 'pages': [
        {'page': 1, 'layout': 'designed', 'standard_reason': None, 'brief': None, 'html_model': 'gemini-3.8-flash'},
        {'page': 2, 'layout': 'standard', 'standard_reason': 'not_designed', 'brief': None, 'html_model': None}]}
    records = {}
    for page in spec.pages:
        value = rb.PageBrief(page=page.index, overall='Dark navy page',
            slots=[rb.SlotBrief(id=c.id, treatment='White card') for c in page.components])
        records[page.index] = {'brief': rb.record(value, page, 'gemini-4-argon'), 'html_model': 'gemini-3.8-flash'}
    for name, content in design_artifacts(spec, folder, records, reset=True).items():
        (folder / name).write_bytes(content)
    response = client.get(base + '/design-pages')
    fixture = json.loads((FIXTURES.parent / 'stage-settings/design_pages.json').read_text(encoding='utf-8'))
    actual = response.json()
    assert actual.keys() == fixture.keys()
    for row, expected in zip(actual['pages'], fixture['pages']):
        assert row.keys() == expected.keys() and row['brief'].keys() == expected['brief'].keys()
        shape(row['brief'], expected['brief'])
        assert row['layout'] == expected['layout'] and row['standard_reason'] == expected['standard_reason']
        assert row['html_model'] == expected['html_model']


def pending_review_fixture(app, build_id, name='design_pages.review.json'):
    """Seed only the durable review envelope; these contract tests must not generate a page."""
    from dss.memory import episodic
    fixture = json.loads((FIXTURES.parent / 'stage-settings' / name).read_text(encoding='utf-8'))
    record = {'review': fixture['review'], 'owner': 'r_contractreview',
              'folder': str(app.state.settings.get().data_dir / 'unused-candidate'),
              'state': {}, 'fingerprint': 'unneeded-before-conflict'}
    episodic.save_brief_review(app.state.db, build_id, record)
    return fixture


@pytest.mark.parametrize('name', ['design_pages.review.json', 'design_pages.review.issue.json'])
def test_pending_design_pages_review_contract(client, app, build_id, name):
    fixture = pending_review_fixture(app, build_id, name)
    response = client.get(f'/api/builds/{build_id}/design-pages')
    assert response.status_code == 200, response.text
    shape(response.json(), fixture)
    assert response.json()['review'] == fixture['review']
    assert response.json()['pages'] == []


def test_pending_brief_review_guards_every_mutating_build_route(client, app, build_id, monkeypatch):
    import re
    pending_review_fixture(app, build_id)
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: pytest.fail('pending review started a model'))
    exceptions = {('PUT', '/api/builds/{build_id}/briefs/review'),
                  ('POST', '/api/builds/{build_id}/briefs/review/approve'),
                  ('POST', '/api/builds/{build_id}/briefs/review/cancel')}
    def effective_routes(routes):
        # FastAPI 0.159 keeps include_router branches rather than flattening app.routes.
        # Their effective candidates carry the combined prefix and include hidden routes too.
        for route in routes:
            candidates = getattr(route, 'effective_candidates', None)
            if callable(candidates):
                yield from effective_routes(candidates())
            else:
                yield route
    checked = set()
    for route in effective_routes(app.routes):
        path = getattr(route, 'path', '')
        if not path.startswith('/api/builds/{build_id}/'):
            continue
        for method in getattr(route, 'methods', set()) & {'POST', 'PUT', 'PATCH', 'DELETE'}:
            if (method, path) in exceptions:
                continue
            url = re.sub(r'\{[^}]+\}', 'example', path.replace('{build_id}', build_id))
            response = client.request(method, url, json={})
            assert response.status_code == 409, (method, path, response.text)
            assert response.json()['error']['code'] == 'brief_review_pending', (method, path, response.text)
            checked.add((method, path))
    assert {('POST', '/api/builds/{build_id}/blueprint/accept'),
            ('POST', '/api/builds/{build_id}/comments'),
            ('POST', '/api/builds/{build_id}/versions'),
            ('POST', '/api/builds/{build_id}/sources')} <= checked
    assert client.get(f'/api/builds/{build_id}').status_code == 200
    assert client.put('/api/settings', json={'review_briefs': False}).status_code == 200
    assert client.get(f'/api/builds/{build_id}/design-pages').json()['review'] is not None


@pytest.mark.parametrize('endpoint,body_key', [('', 'brief'), ('/approve', 'sha256')])
def test_brief_review_old_revision_is_contract_conflict(client, app, build_id, monkeypatch, endpoint, body_key):
    review = pending_review_fixture(app, build_id, 'design_pages.review.issue.json')['review']
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: pytest.fail('old revision reached a model'))
    body = {'review_id': review['review_id'], 'revision': review['revision'] - 1,
            body_key: review['brief']['brief'] if body_key == 'brief' else review['brief']['sha256']}
    response = client.request('POST' if endpoint else 'PUT',
                              f'/api/builds/{build_id}/briefs/review{endpoint}', json=body)
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'brief_review_conflict'
    assert response.json()['error']['detail']['revision'] == review['revision']


def test_brief_review_another_sha_is_contract_conflict(client, app, build_id, monkeypatch):
    review = pending_review_fixture(app, build_id)['review']
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: pytest.fail('wrong sha reached a model'))
    response = client.post(f'/api/builds/{build_id}/briefs/review/approve', json={
        'review_id': review['review_id'], 'revision': review['revision'], 'sha256': '0' * 64})
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'brief_review_conflict'
    assert response.json()['error']['detail']['revision'] == review['revision']


def test_cancelling_approved_brief_review_returns_current_build_idempotently(client, app, build_id):
    from dss.memory import episodic
    review = pending_review_fixture(app, build_id)['review']
    row = episodic.brief_review(app.state.db, build_id, review['review_id'])
    episodic.update_brief_review(app.state.db, row, row['record'], state='approved', run_id='r_contractapproved')
    expected = client.get(f'/api/builds/{build_id}').json()
    for _ in range(2):
        response = client.post(f'/api/builds/{build_id}/briefs/review/cancel', json={'review_id': review['review_id']})
        assert response.status_code == 200, response.text
        assert response.json() == expected
    row = episodic.brief_review(app.state.db, build_id, review['review_id'])
    assert row['state'] == 'approved' and row['run_id'] == 'r_contractapproved'


async def test_stage_calls_and_build_cost_contracts(client, app, build_id):
    from copy import deepcopy
    from dss.harness import stages
    from dss.harness.tracing import Trace
    from fakes import FakeLLM
    from google.genai import types
    fixture = json.loads((FIXTURES.parent / 'stage-settings/run_calls.json').read_text())
    cost_fixture = json.loads((FIXTURES.parent / 'stage-settings/build_cost.json').read_text())
    saved = deepcopy(stages.snapshot(app.state.settings.get()))
    class Priced(FakeLLM):
        model: str = stages.FLASH
        known: bool = False
        async def generate_content_async(self, req, stream=False):
            async for response in super().generate_content_async(req, stream):
                if self.known:
                    response.usage_metadata.thoughts_token_count = 8
                yield response
    partial = await app.state.harness.run('hello', build_id, {}, llm=Priced())
    priced = await app.state.harness.run('hello', build_id, {}, llm=Priced(known=True))
    empty = await app.state.harness.run('create_build', build_id)
    # A completed run's snapshot and calls survive later Settings changes.
    app.state.settings.update({'stages': {'routine': {'thinking': 'high'}}})
    for result, expected in [(partial, None), (priced, (5 * .75 + 10 * 3.75) / 1_000_000), (empty, 0)]:
        response = client.get(f"/api/traces/{result['run_id']}/calls")
        assert response.status_code == 200
        record = response.json()
        assert record.keys() == fixture.keys() and record['settings'] == saved
        assert record['cost_usd_estimate'] == expected and record['cost_complete'] is (expected is not None)
        assert len(record['calls']) == (0 if result is empty else 1)
        for call in record['calls']:
            assert call.keys() == fixture['calls'][0].keys()
            assert call['run_id'] == result['run_id'] and call['stage'] == 'routine' and call['node'] == 'hello'
            assert call['thinking_tokens'] == (8 if result is priced else None)
            assert call['input_measured'] is None and call['input_billed'] == 5 and call['input_enforced'] > 0
            assert call['input_limit'] is None and call['outcome'] == 'ok'
            assert type(call['duration_ms']) is int and call['duration_ms'] >= 0
            assert type(call['started_at']) is str and call['attempt'] == call['transport_attempt'] == 1
            assert not any(word in json.dumps(call) for word in ('test-key', 'Hello!', 'system_instruction', 'provider message'))
    legacy = Trace(app.state.db, 'r_legacy', build_id, 'plan')
    legacy.model, legacy.input_tokens, legacy.output_tokens = stages.FLASH, 100, 20
    legacy.save('ok', None)
    assert client.get('/api/traces/r_legacy/calls').json()['settings'] is None
    response = client.get(f'/api/builds/{build_id}/cost')
    assert response.status_code == 200
    costs = response.json()
    assert costs.keys() == cost_fixture.keys() and costs['complete'] is False
    assert costs['prices_checked_on'] == '2026-10-26'
    assert all(r.keys() == cost_fixture['runs'][0].keys() for r in costs['runs'])
    assert costs['runs'][0]['run_id'] == 'r_legacy' and costs['runs'][0]['basis'] == 'trace'
    assert costs['runs'][0]['complete'] is False and costs['runs'][0]['cost_usd_estimate'] == .00015
    assert costs['cost_usd_estimate'] == pytest.approx(.00015 + (5 * .75 + 10 * 3.75) / 1_000_000)
    assert client.get('/api/traces/unknown/calls').status_code == 404
    assert client.get('/api/traces/unknown/calls').json()['error']['code'] == 'run_not_found'
    assert client.get('/api/builds/unknown/cost').status_code == 404


def test_phase4_contract(thin):
    client, app, bid, folder = thin
    assert client.get("/api/health").json() == {"status":"ok"}
    check(client.get(f"/api/builds/{bid}"), "build.json")
    check(client.get("/api/builds"), "builds.json")
    stage_settings = json.loads((FIXTURES.parent / 'stage-settings/settings.json').read_text())
    shape(client.get('/api/settings').json(), stage_settings)
    shape(client.put('/api/settings', json={'bq_location': 'US'}).json(), stage_settings)
    check(client.get(f"/api/builds/{bid}/messages"), "messages.json")
    check(client.post(f"/api/builds/{bid}/run"), "error.json", 409)
    from test_thin_slice import load_checked
    load_checked(client, bid)
    check(client.post(f"/api/builds/{bid}/recipe"), "recipe.json")
    assert client.get(f"/api/builds/{bid}/spec").json() == json.loads((folder / "spec.json").read_text())
    assert "dss-canvas" in client.get(f"/api/builds/{bid}/prototype").text
    (folder / "docs").mkdir(exist_ok=True)
    (folder / "docs/example.md").write_text("---\ntype: Example\n---\nHello")
    assert client.get(f"/api/builds/{bid}/docs/example.md").text.endswith("Hello")
    (folder / "background_p1.png").write_bytes(b"image")
    assert client.get(f"/api/builds/{bid}/files/background_p1.png").content == b"image"
    assert client.get(f"/api/builds/{bid}/files/%2e%2e").status_code in (400,404)
    check(client.post(f"/api/builds/{bid}/run"), "run_accepted.json", 202)
    settle(client, app)
    check(client.get(f"/api/builds/{bid}"), "build.done.json")
    check(client.post(f"/api/builds/{bid}/versions"), "build.json", 201)
    check(client.get("/api/engine/status"), "engine_status.local.json")
    check(client.post("/api/engine/login"), "run_accepted.json", 202)
    settle(client, app)
    check(client.get("/api/traces"), "traces.json")
    check(client.get(f"/api/traces?build_id={bid}"), "traces.json")
    # Compare real emitted payloads to both 2.0 SSE fixtures. New staged nodes
    # acquire their own endpoint tests as the following tasks implement them.
    examples = {}
    for name in ('events.sse', 'events.usage.sse'):
        for block in (FIXTURES / name).read_text().strip().split('\n\n'):
            lines = block.splitlines()
            examples.setdefault(lines[0].removeprefix('event: '), json.loads(lines[1].removeprefix('data: ')))
    with app.state.db.connect() as conn:
        events = [(r[0], json.loads(r[1])) for r in conn.execute(
            'SELECT kind,payload_json FROM events WHERE build_id=?', (bid,))]
    for kind, payload in events:
        if kind in examples:
            shape(payload, examples[kind])
    assert {'run.started', 'run.finished', 'build.updated', 'stage.changed', 'build.finished'} <= {k for k, _ in events}


def test_recipe_contract_in_agent_mode_without_engine(agent_client, spec):
    client, app, folder = agent_client
    (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    from fakes import ready_fixture
    ready_fixture(app, spec.build_id, folder)
    check(client.post(f"/api/builds/{spec.build_id}/recipe"), "recipe.json")


@pytest.mark.parametrize('stored_stage', ['interview', 'plan', 'context'])
def test_build_2_contract_hides_storage_and_reads_migrated_stages(thin, stored_stage):
    client, app, bid, _ = thin
    values = {'context': 'confirmed', 'outline': 'draft', 'design': 'missing', 'blueprint': 'missing'}
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=?,notes=?,artifacts_json=? WHERE id=?',
                     (stored_stage, 'About these orders', json.dumps(values), bid))
    response = client.get(f'/api/builds/{bid}')
    check(response, 'build.json')
    assert response.json()['stage'] == 'context' and response.json()['notes'] == 'About these orders'
    assert response.json()['artifacts'] == values
    assert not {'ready_for_plan', 'artifacts_json'} & response.json().keys()
    assert client.get('/api/builds').json()[0]['stage'] == 'context'


@pytest.mark.parametrize('mode', ['local', 'agent'])
@pytest.mark.parametrize('field', ['background', 'surface', 'text', 'muted', 'accent', 'palette'])
@pytest.mark.parametrize('color', ['123456', '#abc', '#GG1234'])
def test_corrupted_saved_spec_rejected_without_engine_or_publication(agent_client, spec, mode, field, color, monkeypatch):
    client, app, folder = agent_client
    app.state.config.engine_mode = mode
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    from fakes import ready_fixture
    ready_fixture(app, spec.build_id, folder)
    assert client.post(f'/api/builds/{spec.build_id}/recipe').status_code == 200
    artifacts = {'recipe.jsonl': (folder / 'recipe.jsonl').read_bytes(),
                 'prototype.html': b'complete prototype', 'background_p1.png': b'complete background',
                 'events.jsonl': b'previous events'}
    for name, content in artifacts.items():
        (folder / name).write_bytes(content)
    def no_job(*args, **kwargs):
        raise AssertionError('Invalid recipe prepared an agent job')
    monkeypatch.setattr(app.state.agent_jobs, 'prepare', no_job)
    document = spec.model_dump()
    document['theme'][field] = [color] if field == 'palette' else color
    (folder / 'spec.json').write_text(json.dumps(document), encoding='utf-8')
    for action in ('recipe', 'run'):
        response = client.post(f'/api/builds/{spec.build_id}/{action}')
        assert response.status_code == 422, response.text
        assert response.json().keys() == {'error'}
        assert response.json()['error'].keys() == {'code', 'message', 'detail'}
        assert response.json()['error']['code'] == 'invalid_recipe'
        assert response.json()['error']['detail'] == {}
        assert {name: (folder / name).read_bytes() for name in artifacts} == artifacts
        assert not (folder / 'recipe.jsonl.tmp').exists()
        assert client.get(f'/api/builds/{spec.build_id}').json()['stage'] == 'prototype'
        assert not app.state.engine_busy and not app.state.harness.active_builds
        assert not app.state.engine_tasks
        assert not app.state.agent_jobs.jobs and not app.state.agent_jobs.queue and not app.state.agent_jobs.running
        with app.state.db.connect() as conn:
            assert not conn.execute("SELECT 1 FROM versions WHERE status='building'").fetchone()
            assert not conn.execute("SELECT 1 FROM traces WHERE node='execute'").fetchone()


def test_intake_and_action_contracts(thin, monkeypatch):
    import time
    from fakes import FakeLLM
    from test_intake import FakeBigQuery, SALES
    client, app, bid, folder = thin
    app.state.settings.update({"gcp_project_id":"test-project"})
    fake = FakeBigQuery()
    app.state.bigquery_factory = lambda _: fake
    upload = client.post(f"/api/builds/{bid}/sources/upload", files=[("files", ("sales.csv", SALES, "text/csv"))])
    assert upload.status_code == 201, upload.text
    source_shape = json.loads((FIXTURES / "build.json").read_text())["sources"][0]
    shape(upload.json(), {"sources":[source_shape]})
    for body in ({"kind":"gcs", "uri":"gs://example-bucket/sales.csv"},
                 {"kind":"bigquery", "uri":upload.json()["sources"][0]["bq_table"]}):
        response = client.post(f"/api/builds/{bid}/sources", json=body)
        assert response.status_code == 201, response.text
        shape(response.json(), source_shape)
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: FakeLLM(response="What decision matters most?"))
    def finish():
        for _ in range(500):
            if not app.state.engine_tasks:
                return
            time.sleep(.01)
        raise AssertionError("Action did not finish")
    for route in ('interview/start', 'messages', 'plan'):
        removed = client.post(f'/api/builds/{bid}/{route}', json={'text': 'Compare regional revenue'})
        assert removed.status_code == 404
        assert removed.json() == {'error': {'code': 'not_found', 'message': 'Request could not be handled', 'detail': {}}}
    from dss.memory import episodic
    episodic.save(app.state.db, bid, 'assistant', 'Data connected. Review the context.', 'context')
    check(client.get(f"/api/builds/{bid}/messages"), "messages.json")
    load(client, bid)
    component = client.get(f"/api/builds/{bid}/spec").json()["pages"][0]["components"][0]["id"]
    check(client.post(f"/api/builds/{bid}/comments", json={"comments":[{"component_id":component,"text":"Make it blue"}]}), "run_accepted.json", 202)
    finish()


INTENT = Path(__file__).resolve().parents[2] / "contracts/fixtures/dashboard-intent"


def test_reference_set_contract(thin, monkeypatch):
    """dashboard-intent.md Reference set: exact ReferenceSet keys/types, 202/204, legacy alias, errors."""
    from fakes import FakeLLM
    from dss.spec import references
    from test_audit_style import drain
    from test_references import output, png
    client, app, bid, folder = thin
    monkeypatch.setattr(references, "decode", lambda images: None)
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: FakeLLM(response=output()))
    fixture = json.loads((INTENT / "reference_set.json").read_text())
    response = client.get(f"/api/builds/{bid}/reference-images")
    assert response.status_code == 200 and response.json() is None
    for path, data in (("reference-images", {"mode": "recreate", "instructions": "Use net sales for Revenue."}),
                       ("style-images", {})):
        check(client.post(f"/api/builds/{bid}/{path}", files=[("files", ("a.png", png(), "image/png"))], data=data),
              "run_accepted.json", 202)
        client.portal.call(drain, app)
        result = client.get(f"/api/builds/{bid}/reference-images")
        check(result, "../dashboard-intent/reference_set.json")
        assert result.json()["images"][0]["file"].startswith("reference_img_")
    for content, name, kind, status in ((png() + b"0" * references.MAX_FILE_BYTES, "a.png", "image/png", 413),
                                        (b"text", "a.txt", "text/plain", 422)):
        error = client.post(f"/api/builds/{bid}/reference-images", data={"mode": "recreate"}, files=[("files", (name, content, kind))])
        # error.json's detail is wrong_stage's; upload errors carry detail.reason (existing invalid_source code).
        assert error.status_code == status and error.json()["error"].keys() == {"code", "message", "detail"}
        assert error.json()["error"]["code"] == "invalid_source" and isinstance(error.json()["error"]["detail"]["reason"], str)
    deleted = client.delete(f"/api/builds/{bid}/reference-images")
    assert deleted.status_code == 204 and client.get(f"/api/builds/{bid}/reference-images").json() is None
    assert fixture.keys() == {"id", "mode", "instructions", "images", "summary"}


def test_feasibility_contract_states(thin, monkeypatch):
    """Load the shared fixture explicitly; verify exact shape in every 11.3 state."""
    from dss.spec import requirements as req
    from test_feasibility import check as assess, user, use_model, extracted
    client, app, bid, folder = thin
    fixture = json.loads((INTENT / "feasibility.json").read_text())
    def conform(actual):
        req.Assessment.model_validate(actual)
        expected = {**fixture, "id": actual["id"], "input_digest": actual["input_digest"]}
        shape(actual, expected)
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "unchecked"
    conform(a)
    use_model(monkeypatch, app)
    _, a = assess(client, app, bid)
    assert a["state"] == "ready"
    conform(a)
    sid = user(app, bid, "Animate GPS points along a route")
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale"
    conform(a)
    use_model(monkeypatch, app, extracted(sid, "animation.temporal_playback"))
    _, a = assess(client, app, bid)
    assert a["state"] == "blocked" and a["issues"]
    conform(a)


def test_feasibility_decisions_and_pending_contract(thin, monkeypatch):
    """The fixture's nullable/empty slots also admit the populated contract shapes."""
    from dss.spec import requirements as req
    from test_feasibility import animated, pending, choose, accept
    client, app, bid, folder = thin
    fixture = json.loads((INTENT / "feasibility.json").read_text())
    a = animated(thin, monkeypatch, with_spec=True)
    alternative_shape = {"id": "alt_example", "label": "Time series using observed_at"}
    populated = {**fixture, "issues": [{**fixture["issues"][0], "alternatives": [alternative_shape]}]}
    shape(a, populated)
    b = choose(client, bid, a, accept(a["issues"][0]))
    assert b.status_code == 200
    req.Assessment.model_validate(b.json())
    shape(b.json(), populated)
    a = pending(thin, [{"component_id": "p1_revenue", "text": "Animate this"}])
    populated["pending_comments"] = {"id": "batch_example", "comments": [{"component_id": "p1_revenue", "text": "Animate this"}]}
    shape(client.get(f"/api/builds/{bid}/feasibility").json(), populated)
    req.Assessment.model_validate(a)
    for result in (
        client.post(f"/api/builds/{bid}/feasibility/reapply", json={"assessment_id": "old", "batch_id": "old"}),
        client.delete(f"/api/builds/{bid}/feasibility/pending-comments", params={"assessment_id": "old"}),
    ):
        assert result.status_code == 409 and result.json()["error"]["code"] == "feasibility_stale"
        assert result.json()["error"].keys() == {"code", "message", "detail"}
    result = client.delete(f"/api/builds/{bid}/feasibility/pending-comments", params={"assessment_id": a["id"]})
    assert result.status_code == 200
    populated["pending_comments"] = None
    shape(result.json(), populated)


SYNTHETIC = Path(__file__).resolve().parents[2] / "contracts/fixtures/synthetic-data"


def job_shape(actual, fixture):
    """GenerationStatus: fixture keys/types; source_id and error are nullable either way."""
    assert actual.keys() == fixture.keys()
    for key in ("generation_key", "run_id", "state"):
        assert type(actual[key]) is str
    assert type(actual["retry_ready"]) is bool
    assert actual["state"] in ("queued", "generating", "loading", "succeeded", "failed")
    assert actual["source_id"] is None or type(actual["source_id"]) is str
    assert actual["error"] is None or (actual["error"].keys() == fixture["error"].keys()
                                       and all(type(v) is str for v in actual["error"].values()))


def test_synthetic_data_contract(tmp_path, monkeypatch):
    """synthetic-data.md 1.1 / api.md 1.4: request, GenerationStatus, Source and dataset shapes."""
    from fastapi.testclient import TestClient
    from dss.config import Config
    from dss.data.synthetic import parse_spec
    from dss.main import create_app
    from fakes import fake_models
    from test_synthetic_api import FakeTypedBigQuery, create, wait
    request = json.loads((SYNTHETIC / "request.json").read_text())
    failed = json.loads((SYNTHETIC / "job.failed.json").read_text())
    succeeded = json.loads((SYNTHETIC / "job.succeeded.json").read_text())
    example = json.loads((SYNTHETIC / "dataset.json").read_text())
    source = json.loads((SYNTHETIC / "source.json").read_text())
    proposal = json.loads((SYNTHETIC / "proposal.json").read_text())
    assert parse_spec(proposal["spec"]) == parse_spec(request["spec"])
    fake = FakeTypedBigQuery()
    app = create_app(Config(data_dir=tmp_path, gcp_project_id="test-project"),
                     model_lister=fake_models, bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        bid = create(client)
        # The fixture names a proposal; none is current, so it is stale.
        stale = client.post(f"/api/builds/{bid}/synthetic-data", json=request)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "synthetic_proposal_stale"
        assert stale.json()["error"].keys() == {"code", "message", "detail"}
        accepted = client.post(f"/api/builds/{bid}/synthetic-data", json={**request, "proposal_id": None})
        check(accepted, "run_accepted.json", 202)
        wait(app)
        key = request["generation_key"]
        status = client.get(f"/api/builds/{bid}/synthetic-data/jobs/{key}").json()
        job_shape(status, failed)
        shape(status, succeeded)
        assert status["state"] == "succeeded" and status["source_id"] and status["error"] is None
        jobs = client.get(f"/api/builds/{bid}/synthetic-data/jobs").json()
        assert jobs == [status]
        [registered] = client.get(f"/api/builds/{bid}").json()["sources"]
        shape(registered, source)
        assert registered["kind"] == source["kind"] and registered["name"] == source["name"]
        assert registered["row_count"] == source["row_count"]
        [dataset] = client.get(f"/api/builds/{bid}/synthetic-data").json()
        # shape() compares list items with the first; spec columns differ by generator, so compare exactly.
        assert dataset.keys() == example.keys() and dataset["spec"] == request["spec"]
        shape({k: v for k, v in dataset.items() if k != "spec"}, {k: v for k, v in example.items() if k != "spec"})
        # The fixture's checksum came from the generator on request.json's spec: end-to-end determinism.
        assert {k: dataset[k] for k in ("sha256", "bytes", "generator_version", "synthetic")} == {
            k: example[k] for k in ("sha256", "bytes", "generator_version", "synthetic")}
        assert parse_spec(dataset["spec"]) == parse_spec(request["spec"])
        assert all(type(text) is str and len(text) <= 240 for text in dataset["assumptions"])
        assert client.get(f"/api/builds/{bid}/synthetic-data/{status['source_id']}/csv").status_code == 200
        # A failed job matches the failed fixture exactly in shape.
        fake.drop = 1
        other = create(client)
        assert client.post(f"/api/builds/{other}/synthetic-data", json={**request, "proposal_id": None}).status_code == 202
        wait(app)
        failure = client.get(f"/api/builds/{other}/synthetic-data/jobs/{key}").json()
        job_shape(failure, failed)
        assert {k: failure[k] for k in ("state", "source_id", "retry_ready")} == {
            k: failed[k] for k in ("state", "source_id", "retry_ready")}
        assert failure["error"]["code"] == failed["error"]["code"]
        conflict = client.post(f"/api/builds/{other}/synthetic-data", json={**request, "proposal_id": None, "spec": {**request["spec"], "seed": 1}})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "synthetic_request_conflict"


def test_synthetic_proposal_contract(tmp_path, monkeypatch):
    """Current Proposal matches the shared fixture and preserves assumptions on acceptance."""
    from fastapi.testclient import TestClient
    from dss.config import Config
    from dss.data.synthetic import parse_spec
    from dss.main import create_app
    from fakes import fake_models
    from test_synthetic_api import FakeTypedBigQuery, create, wait, recreate_reference, proposal_model
    fixture = json.loads((SYNTHETIC / 'proposal.json').read_text())
    app = create_app(Config(data_dir=tmp_path, gcp_project_id='test-project'),
                     model_lister=fake_models, bigquery_factory=lambda _: FakeTypedBigQuery())
    with TestClient(app) as client:
        bid = create(client)
        url = f'/api/builds/{bid}/synthetic-data/proposal'
        assert client.get(url).status_code == 200 and client.get(url).json() is None
        rid = recreate_reference(client, app, bid, monkeypatch)
        model = proposal_model(monkeypatch, app, {k: fixture[k] for k in ('spec', 'assumptions')})
        response = client.post(url, json={'reference_set_id': rid})
        check(response, 'run_accepted.json', 202)
        wait(app)
        proposed = client.get(url)
        assert proposed.status_code == 200
        proposal = proposed.json()
        assert proposal.keys() == fixture.keys()
        shape({k: v for k, v in proposal.items() if k != 'spec'},
              {k: v for k, v in fixture.items() if k != 'spec'})
        assert parse_spec(proposal['spec']) == parse_spec(fixture['spec'])
        assert proposal['reference_set_id'] == rid and proposal['assumptions'] == fixture['assumptions']
        response = client.post(f'/api/builds/{bid}/synthetic-data', json={
            'generation_key': 'accept_proposal', 'proposal_id': proposal['id'], 'spec': proposal['spec']})
        check(response, 'run_accepted.json', 202)
        wait(app)
        dataset, = client.get(f'/api/builds/{bid}/synthetic-data').json()
        assert dataset['spec'] == proposal['spec'] and dataset['assumptions'] == proposal['assumptions']
        assert model.calls == 1
