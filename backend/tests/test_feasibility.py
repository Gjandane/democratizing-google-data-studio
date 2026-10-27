"""Task 11.3: bounded extraction, code-owned classification, persistence and invalidation."""
import copy
import json
import time
from pathlib import Path

import pytest

from dss.harness.context import BUDGETS, requirement_sections
from dss.memory import episodic
from dss.spec import capabilities, requirements as req
from fakes import FakeLLM
from test_audit_style import drain
from test_references import Capture, output, png
from test_thin_slice import thin, load


def check(client, app, bid):
    result = client.post(f"/api/builds/{bid}/feasibility/check")
    assert result.status_code == 202, result.text
    client.portal.call(drain, app)
    return result.json()["run_id"], client.get(f"/api/builds/{bid}/feasibility").json()


def extracted(source_id, capability="chart.bar", text="Show a bar chart", **kwargs):
    return {"source_id": source_id, "text": text, "needs": [{"capability": capability}], **kwargs}


def user(app, bid, text):
    return episodic.save(app.state.db, bid, "user", text)["id"]


def use_model(monkeypatch, app, *items):
    model = Capture(response=json.dumps({"requirements": list(items)}), requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    return model


def source(app, bid, **fields):
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", ("s_test", bid, "bigquery", "sales", "p.d.t", 10,
            json.dumps([{"name": name, "type": kind} for name, kind in fields.items()])))


@pytest.mark.parametrize('mode', ['local', 'agent'])
@pytest.mark.parametrize('state', ['unchecked', 'stale', 'blocked', 'prototype_stale', 'pending_comments', 'allowlist'])
def test_execution_gate_has_no_side_effects(thin, monkeypatch, mode, state):
    from dss.api import run
    client, app, bid, folder = thin
    load(client, bid)
    use_model(monkeypatch, app)
    if state != 'unchecked':
        _, ready = check(client, app, bid)
        assert ready['state'] == 'ready' and not ready['prototype_stale']
    ledger = req.load(folder)
    if state == 'stale':
        user(app, bid, 'New unassessed request')
    elif state == 'blocked':
        ledger.scope_error = 'Reduce the scope'
        req.save(folder, ledger, req.evaluate(req.inputs(app.state.db, bid, folder), ledger, capabilities.Checker(capabilities.load_registry())))
    elif state == 'prototype_stale':
        ledger.prototype_stale = True
        req.save(folder, ledger)
    elif state == 'pending_comments':
        ledger = req.stage_comments(ledger, [{'component_id': 'p1_revenue', 'text': 'Animate GPS'}])
        req.save(folder, ledger)
    elif state == 'allowlist':
        monkeypatch.setenv('DSS_ALLOWED_TYPES', 'text')
    app.state.config.engine_mode = mode
    # A pre-existing recipe never grants permission. Even an offline agent must
    # not hide the intent refusal behind a deployment precondition.
    (folder / 'recipe.jsonl').write_bytes(b'previous complete recipe\n')
    before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    def refuse(*args, **kwargs):
        pytest.fail('blocked request reached compilation or job preparation')
    monkeypatch.setattr(run, 'compile_recipe', refuse)
    monkeypatch.setattr(run, 'compile_current', refuse)
    monkeypatch.setattr(app.state.agent_jobs, 'prepare', refuse)
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT count(*) FROM traces').fetchone()[0]
    for endpoint in ('recipe', 'run'):
        response = client.post(f'/api/builds/{bid}/{endpoint}')
        assert response.status_code == 409, response.text
        error = response.json()['error']
        assert error['code'] == 'feasibility_blocked'
        assert set(error['detail']) == {'assessment_id', 'issue_ids'}
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not app.state.engine_busy and not app.state.engine_tasks and not app.state.harness.active_builds
    assert not app.state.agent_jobs.jobs
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces').fetchone()[0] == traces
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'


def test_legacy_and_supported_no_image_recover_before_execution(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f'/api/builds/{bid}/recipe').json()['error']['code'] == 'feasibility_blocked'
    model = use_model(monkeypatch, app)
    _, assessment = check(client, app, bid)
    assert assessment['state'] == 'ready' and not assessment['prototype_stale']
    assert model.calls == 0
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    assert client.post(f'/api/builds/{bid}/run').status_code == 202
    client.portal.call(drain, app)
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'done'


def test_new_version_copies_intent_without_authorization(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, 'Show a bar chart of sum revenue by region')
    animation_id = user(app, bid, 'Animate GPS points along a route')
    use_model(monkeypatch, app, extracted(sid, component_ids=['p1_regions'],
        mappings=[{'label': 'Revenue', 'field': 'revenue', 'aggregation': 'sum'}]),
        extracted(animation_id, 'animation.temporal_playback', 'Animate GPS points along a route'))
    _, blocked = check(client, app, bid)
    assessment = choose(client, bid, blocked, drop(blocked['issues'][0])).json()
    assert assessment['state'] == 'ready'
    # Keep representative reference bytes/observations. Style is already fulfilled
    # by the existing prototype; this fixture establishes the copied input proof.
    reference = {'id': 'ref_copy', 'mode': 'style', 'instructions': '', 'images': [
        {'id': 'img_copy', 'name': 'reference.png', 'file': 'reference_img_copy.png'}],
        'summary': 'Blue', 'interpretation': {}}
    (folder / 'references.json').write_text(json.dumps(reference), encoding='utf-8')
    (folder / 'reference_img_copy.png').write_bytes(png())
    ledger = req.load(folder)
    snapshot, checker = req.inputs(app.state.db, bid, folder), capabilities.Checker(capabilities.load_registry())
    req.save(folder, ledger, req.evaluate(snapshot, ledger, checker))
    before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    response = client.post(f'/api/builds/{bid}/versions')
    assert response.status_code == 201, response.text
    destination = folder.parent / 'v2'
    copied = req.load(destination)
    assert copied.assessment is None and copied.verification == {}
    assert copied.requirements == ledger.requirements and copied.decisions == ledger.decisions
    assert (destination / 'references.json').read_bytes() == (folder / 'references.json').read_bytes()
    assert (destination / 'reference_img_copy.png').read_bytes() == png()
    assert all(p.read_bytes() == value for p, value in before.items())
    assert client.get(f'/api/builds/{bid}/feasibility').json()['state'] == 'unchecked'
    for endpoint in ('recipe', 'run'):
        assert client.post(f'/api/builds/{bid}/{endpoint}').json()['error']['code'] == 'feasibility_blocked'
    _, fresh = check(client, app, bid)
    assert fresh['state'] == 'ready' and fresh['id'] != assessment['id']
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200


@pytest.mark.parametrize('slot', ['component', 'logo'])
@pytest.mark.parametrize('path', ['reference_img_123.png', 'images/reference_img_123.png', 'Reference_img_123.png',
                                  'sub\\REFERENCE_img_123.png'])
def test_screenshot_cannot_replace_bound_charts(thin, monkeypatch, slot, path):
    from dss.recipe.compiler import compile_recipe
    from dss.render.prototype import image_url
    from dss.spec.models import DashboardSpec
    from dss.spec.validate import validate_spec
    client, app, bid, folder = thin
    load(client, bid)
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    page = spec.pages[0]
    if slot == 'component':
        page.components[0].type = 'image'
        page.components[0].image_path = path
    else:
        # Logos are flattened into the recipe background image.
        page.decorations.append(page.decorations[0].model_copy(update={
            'id': 'p1_logo', 'kind': 'logo', 'text': None, 'style': {'image_path': path}}))
    with pytest.raises(ValueError, match='Reference screenshots'):
        compile_recipe(spec, 1)
    # Plan/revise validation refuses it before any prototype is published.
    assert any('Reference screenshots' in e['message'] for e in validate_spec(spec))
    (folder / 'reference_img_123.png').write_bytes(png())
    with pytest.raises(ValueError, match='Reference screenshots'):
        image_url(path, folder)
    # Through the API: a ready build with such a spec compiles and starts nothing.
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    use_model(monkeypatch, app)
    check(client, app, bid)
    (folder / 'recipe.jsonl').write_bytes(b'previous complete recipe\n')
    for endpoint in ('recipe', 'run'):
        response = client.post(f'/api/builds/{bid}/{endpoint}')
        assert response.status_code in (409, 422), response.text
    client.portal.call(drain, app)
    assert (folder / 'recipe.jsonl').read_bytes() == b'previous complete recipe\n'
    assert not app.state.engine_tasks and not app.state.agent_jobs.jobs


def test_confirmed_reapply_compiles_runs_and_carries_to_new_version(thin, monkeypatch):
    from dss.spec.models import DataField
    from test_revise import seed_revision, CommentFlow, response, op, post_batch, reapply_batch
    client, app, bid, folder = thin
    _, _, _, spec, *_ = seed_revision(app, bid, monkeypatch)
    spec.datasource.fields.append(DataField(name='observed_at', type='DATE', label='Observed at', role='dimension'))
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    fake = CommentFlow(needs_by_text={'Animate GPS': [{'capability': 'animation.temporal_playback'}]}, response=response([
        op('/pages/0/components/0/type', 'time_series'), op('/pages/0/components/0/date_dimension', 'observed_at'),
        op('/pages/0/components/0/grid/h', 10)]))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: fake)
    a = post_batch(client, app, bid, [{'component_id': 'p1_revenue', 'text': 'Animate GPS'}])
    chosen = choose(client, bid, a, accept(a['issues'][0]))
    assert chosen.status_code == 200
    a = client.get(f'/api/builds/{bid}/feasibility').json()
    a = reapply_batch(client, app, bid, a)
    assert a['state'] == 'ready' and not a['prototype_stale']
    decisions = req.load(folder).decisions
    assert decisions[0]['applied']
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    assert client.post(f'/api/builds/{bid}/run').status_code == 202
    client.portal.call(drain, app)
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'done'
    assert client.post(f'/api/builds/{bid}/versions').status_code == 201
    destination = folder.parent / 'v2'
    assert req.load(destination).assessment is None and req.load(destination).decisions == decisions
    _, a = check(client, app, bid)
    assert a['state'] == 'ready' and a['issues'][0]['resolution'] == 'accepted_alternative'
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    assert fake.extractions == 1 and fake.revisions == 1
    # Changing a prerequisite must revoke the carried choice before queuing again.
    data = json.loads((destination / 'spec.json').read_text(encoding='utf-8'))
    data['datasource']['fields'] = [f for f in data['datasource']['fields'] if f['name'] != 'observed_at']
    (destination / 'spec.json').write_text(json.dumps(data), encoding='utf-8')
    for endpoint in ('recipe', 'run'):
        result = client.post(f'/api/builds/{bid}/{endpoint}')
        assert result.status_code == 409 and result.json()['error']['code'] == 'feasibility_blocked'
    _, a = check(client, app, bid)
    assert a['state'] == 'blocked' and any(i['resolution'] == 'unresolved' for i in a['issues'])


def test_legacy_check_one_trace_no_side_effects(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assets = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    model = use_model(monkeypatch, app)
    assert client.get(f"/api/builds/{bid}/feasibility").json() == req.Assessment().model_dump()
    run, result = check(client, app, bid)
    assert result["state"] == "ready" and result["id"] and result["input_digest"]
    assert model.calls == 0  # Deterministic legacy spec check needs no extraction.
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM traces WHERE run_id=?", (run,)).fetchone()[0] == 1
        events = [r[0] for r in conn.execute("SELECT kind FROM events WHERE run_id=? ORDER BY rowid", (run,))]
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE run_id=?", (run,)).fetchone()[0])
    assert events[0] == "run.started" and events[-1] == "run.finished" and "docs.updated" in events
    assert "capability_check" in [s["node"] for s in spans]
    assert all((folder / name).read_bytes() == value for name, value in assets.items())
    assert not (folder / "recipe.jsonl").exists()
    assert "Feasibility" in client.get(f"/api/builds/{bid}/docs/feasibility.md").text
    ledger_bytes = (folder / "requirements.json").read_bytes()
    for _ in range(3):
        assert client.get(f"/api/builds/{bid}/feasibility").json() == result
    assert model.calls == 0 and (folder / "requirements.json").read_bytes() == ledger_bytes


def test_extraction_keeps_provenance_and_mapping(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Bar chart: revenue by region, sum, USD, month")
    source(app, bid, revenue="FLOAT", region="STRING")
    model = use_model(monkeypatch, app, extracted(sid, mappings=[{"label": "Revenue", "field": "revenue",
        "aggregation": "sum", "unit": "USD", "date_grain": "month"}]))
    run, result = check(client, app, bid)
    assert result["state"] == "ready", result
    assert model.calls == 1
    ledger = req.load(folder)
    r = ledger.requirements[0]
    assert r.source.id == sid and r.source.kind == "message"
    assert r.mappings[0].model_dump() == {"label": "Revenue", "field": "revenue", "aggregation": "sum", "unit": "USD", "date_grain": "month"}
    evidence = ledger.verification[r.id]
    assert evidence[0]["status"] == "supported" and evidence[0]["evidence"]
    assert evidence[1]["schema_type"] == "FLOAT" and evidence[1]["source_id"] == sid
    first_id = r.id
    check(client, app, bid)
    assert model.calls == 1 and req.load(folder).requirements[0].id == first_id
    request = model.requests[0]
    assert request.config.max_output_tokens == 8000
    assert BUDGETS["capability_check"] == 24000 and not request.config.tools
    assert "source_id" in json.dumps(request.config.response_json_schema)


@pytest.mark.parametrize("capability,status", [
    ("feature.telepathy", "unknown"), ("animation.temporal_playback", "unsupported_app"),
    ("extension.community_visualization", "unsupported_app"), ("element.shape", "unsupported_app"),
    ("geo.lat_long_points", "unsupported_app"), ("chart.time_series", "needs_data")])
def test_code_classifies_support_scopes(thin, monkeypatch, capability, status):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show the requested behavior")
    use_model(monkeypatch, app, extracted(sid, capability))
    _, result = check(client, app, bid)
    assert result["state"] == "blocked" and result["issues"][0]["status"] == status
    assert result["issues"][0]["resolution"] == "unresolved"
    if status == "unknown":
        assert "clarify" in result["issues"][0]["reason"]


def test_gross_net_model_suggestion_requires_definition(thin, monkeypatch):
    client, app, bid, folder = thin
    source(app, bid, gross_sales="FLOAT", net_sales="FLOAT")
    sid = user(app, bid, "Show Revenue")
    use_model(monkeypatch, app, extracted(sid, "chart.scorecard", mappings=[{"label": "Revenue", "field": "gross_sales",
        "unit": "USD", "aggregation": "sum", "date_grain": "month"}]))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "needs_clarification"
    assert "gross_sales" in a["issues"][0]["reason"]


def test_native_product_exclusion_is_distinct(thin, monkeypatch):
    """The seed has no proven product exclusions; exercise the registry's supported state shape."""
    client, app, bid, folder = thin
    raw = capabilities.load_registry().model_dump(mode="json")
    # 24.1: the fixed-size list became app-supported (recipe 1.3); shapes have no recipe op.
    cap = next(c for c in raw["capabilities"] if c["id"] == "element.shape")
    cap["native_product"]["status"] = "unsupported"
    registry = capabilities.Registry.model_validate(raw)
    monkeypatch.setattr("dss.harness.nodes.capability_check.load_registry", lambda: registry)
    monkeypatch.setattr("dss.api.feasibility.load_registry", lambda: registry)
    sid = user(app, bid, "A product-excluded feature")
    use_model(monkeypatch, app, extracted(sid, "element.shape"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unsupported_product"


@pytest.mark.parametrize("count,finish,raw,error", [(8001, "STOP", None, None),
    (8000, "MAX_TOKENS", '{"requirements":[', None), (100, "MAX_TOKENS", '{"requirements":[', 'MAX_TOKENS')])
def test_output_token_limit_blocks_without_repair(thin, monkeypatch, count, finish, raw, error):
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    client, app, bid, folder = thin
    sid = user(app, bid, "Show a bar")
    class OverOutput(FakeLLM):
        async def generate_content_async(self, request, stream=False):
            self.calls += 1
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=self.response)]),
                finish_reason=types.FinishReason(finish), error_code=error,
                usage_metadata=types.GenerateContentResponseUsageMetadata(candidates_token_count=count))
    model = OverOutput(response=raw or json.dumps({"requirements": [extracted(sid)]}))
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and model.calls == 1
    # 24.3: the refusal names the limit and the reported size, never a bare "reduce the scope".
    assert a["issues"][0]["reason"] == f"Requirement check output reached its 8,000-token limit ({count:,} tokens reported)"


def test_gemini_extraction_reserves_bounded_output_for_json(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, 'Show a bar')
    model = use_model(monkeypatch, app, extracted(sid))
    model.model = 'gemini-3.8-flash'
    check(client, app, bid)
    config = model.requests[0].config
    assert config.max_output_tokens == 8000
    assert config.thinking_config.thinking_level == 'LOW'


@pytest.mark.parametrize("text,field,agg,state", [
    ("Show Revenue; I have gross_sales and net_sales", "gross_sales", "sum", "blocked"),
    ("Revenue is gross_sales or net_sales; sum in USD by month", "gross_sales", "sum", "blocked"),
    ("Do not use gross_sales for Revenue", "gross_sales", None, "blocked"),
    ("For the regional sales director, Revenue means net_sales; sum in USD by month", "net_sales", "sum", "ready"),
    ("For our CFO, use net_sales for Revenue; sum in USD by month", "net_sales", "sum", "ready"),
    ("For the global finance manager, Revenue means net_sales; sum in USD by month", "net_sales", "sum", "ready"),
    ("For the CFO if asked, Revenue means gross_sales; sum in USD by month", "gross_sales", "sum", "blocked"),
    ("For the regional sales director, do not use gross_sales for Revenue; sum in USD by month", "gross_sales", "sum", "blocked"),
    ("If we ever change it, Revenue means gross_sales; sum in USD by month", "gross_sales", "sum", "blocked"),
    ("Use net_sales for Revenue; sum in USD by month", "net_sales", "sum", "ready"),
    ("Revenue means net_sales; average in USD by month", "net_sales", "sum", "blocked"),
    ("Revenue means net_sales; average in USD by month", "net_sales", "avg", "ready")])
def test_mapping_definition_and_aggregation_are_not_inferred(thin, monkeypatch, text, field, agg, state):
    client, app, bid, folder = thin
    source(app, bid, gross_sales="FLOAT", net_sales="FLOAT")
    sid = user(app, bid, text)
    use_model(monkeypatch, app, extracted(sid, mappings=[{"label": "Revenue", "field": field,
        "aggregation": agg, "unit": "USD", "date_grain": "month"}]))
    _, a = check(client, app, bid)
    assert a["state"] == state
    if state == "blocked":
        assert all(i["status"] == "needs_clarification" for i in a["issues"])


@pytest.mark.parametrize('text,grain,ready', [('Show daily revenue trend', 'day', True),
    ('Show monthly revenue trend', 'month', True), ('Show monthly revenue trend', 'day', False)])
def test_date_grain_preserves_daily_and_monthly_meaning(text, grain, ready):
    mapping = req.Mapping(label='revenue', field='revenue', date_grain=grain)
    requirement = req.Requirement(id='r', source=req.Source(id='m', kind='message', text=text), text=text, mappings=[mapping])
    assert (req.mapping_verdict(mapping, requirement, {'revenue': 'FLOAT'}) is None) == ready


@pytest.mark.parametrize('text,label,field,agg,ok', [
    ('Order count is COUNT(DISTINCT order_id).', 'order count', 'order_id', 'count_distinct', True),
    ('Order count is COUNT(DISTINCT order_id).', 'order count', 'order_id', 'count', False),
    ('Order count is COUNT(order_id).', 'order count', 'order_id', 'count', True),
    ('Order count is the distinct count of order_id.', 'order count', 'order_id', 'count_distinct', True),
    ('Show the order count; use order_id for order count.', 'order count', 'order_id', 'count', False),
    ('Show the order count; use order_id for order count.', 'order count', 'order_id', 'count_distinct', False),
    ('Total revenue is SUM(revenue).', 'revenue', 'revenue', 'sum', True),
    ('Total revenue is SUM(revenue).', 'revenue', 'revenue', 'avg', False),
    # DISTINCT qualifies only COUNT; SUM(DISTINCT x) is no definition the ledger can hold.
    ('Revenue is SUM(DISTINCT gross_sales).', 'revenue', 'gross_sales', 'sum', False),
    ('Revenue is the sum of distinct gross_sales.', 'revenue', 'gross_sales', 'sum', False),
    ('Revenue is SUM(gross_sales) unless audited.', 'revenue', 'gross_sales', 'sum', False),
    ('Do not use SUM(gross_sales) for revenue.', 'revenue', 'gross_sales', 'sum', False)])
def test_explicit_aggregate_definitions(text, label, field, agg, ok):
    mapping = req.Mapping(label=label, field=field, aggregation=agg)
    requirement = req.Requirement(id='r', source=req.Source(id='m', kind='message', text=text), text=text, mappings=[mapping])
    fields = {'order_id': 'STRING', 'revenue': 'FLOAT', 'gross_sales': 'FLOAT'}
    assert (req.mapping_verdict(mapping, requirement, fields) is None) == ok


def merge_turns(fields, *turns):
    snapshot = {'sources': [{'id': 's', 'table': 't', 'columns': [{'name': n, 'type': k, 'bq_type': k} for n, k in fields.items()]}],
                'incoming': [], 'reference': None, 'definitions': {}, 'spec': None}
    ledger = req.Ledger()
    for i, (text, items) in enumerate(turns):
        snapshot['incoming'].append(req.Source(id=f'm{i}', kind='message', text=text).model_dump())
        ledger = req.merge(ledger, snapshot, req.Extraction(requirements=[{'source_id': f'm{i}', **item} for item in items]))
    return snapshot, ledger


def test_quoted_coordinated_formulas_never_authorize_middle_clauses():
    text = '"Revenue is SUM(revenue); order count is COUNT(DISTINCT order_id); quantity sold is SUM(quantity)."'
    m = req.Mapping(label='order count', field='order_id', aggregation='count_distinct')
    row = req.Requirement(id='r', source=req.Source(id='s', kind='message', text=text), text=text)
    assert req.mapping_verdict(m, row, {'order_id': 'STRING'}) is not None


def test_absorbed_unit_definition_blocks_incompatible_reuse_and_allows_correction():
    start = ('Show Revenue', [{'text': 'Show Revenue', 'needs': [{'capability': 'chart.scorecard'}],
        'mappings': [{'label': 'Revenue', 'field': None}]}])
    define = ('Revenue is SUM(revenue) in USD.', [{'text': 'Revenue is SUM(revenue) in USD.',
        'mappings': [{'label': 'Revenue', 'field': 'revenue', 'aggregation': 'sum', 'unit': 'USD'}]}])
    ask = ('Show Revenue in EUR', [{'text': 'Show Revenue in EUR', 'needs': [{'capability': 'chart.scorecard'}],
        'mappings': [{'label': 'Revenue', 'field': 'revenue', 'unit': 'EUR'}]}])
    correction = ('Correction: Revenue is SUM(revenue) in EUR.', [{'text': 'Correction: Revenue is SUM(revenue) in EUR.',
        'mappings': [{'label': 'Revenue', 'field': 'revenue', 'aggregation': 'sum', 'unit': 'EUR'}]}])
    checker = capabilities.Checker(capabilities.load_registry())
    snapshot, ledger = merge_turns({'revenue': 'FLOAT'}, start, define, ask)
    assert req.evaluate(snapshot, ledger, checker).state == 'blocked'
    snapshot, ledger = merge_turns({'revenue': 'FLOAT'}, start, define, ask, correction)
    assert req.evaluate(snapshot, ledger, checker).state == 'ready'
    assert all(m.unit == 'EUR' for row in ledger.requirements for m in row.mappings)


def test_normal_explicit_reconfirmation_rebinds_changed_source():
    text = 'Revenue is SUM(revenue).'
    item = {'text': text, 'needs': [{'capability': 'chart.scorecard'}],
            'mappings': [{'label': 'Revenue', 'field': 'revenue', 'aggregation': 'sum'}]}
    snapshot, ledger = merge_turns({'revenue': 'FLOAT'}, (text, [item]))
    snapshot['sources'][0]['table'] = 'other'
    ledger = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    checker = capabilities.Checker(capabilities.load_registry())
    assert req.evaluate(snapshot, ledger, checker).state == 'blocked'
    snapshot['incoming'].append(req.Source(id='reconfirm', kind='message', text=text).model_dump())
    ledger = req.merge(ledger, snapshot, req.Extraction(requirements=[{'source_id': 'reconfirm', **item}]))
    assert req.evaluate(snapshot, ledger, checker).state == 'ready'


@pytest.mark.parametrize('answer,rows', [
    # Each definition clause refines its earlier row, wherever it sits in the answer.
    ('Order count is COUNT(DISTINCT order_id). Quantity sold is SUM(quantity). Thanks!', 2),
    # A clause that is not a definition keeps the whole answer as a fail-closed row.
    ('Order count is COUNT(DISTINCT order_id). Quantity sold is SUM(quantity). Animate GPS points.', 3)])
def test_definition_answers_refine_and_keep_other_clauses(answer, rows):
    fields = {'order_id': 'STRING', 'quantity': 'INTEGER'}
    snapshot, ledger = merge_turns(fields, ('Track order count and quantity sold', [
        {'text': 'Track order count', 'needs': [{'capability': 'chart.scorecard'}], 'mappings': [{'label': 'order count', 'field': None}]},
        {'text': 'Track quantity sold', 'needs': [{'capability': 'chart.scorecard'}], 'mappings': [{'label': 'quantity sold', 'field': None}]}]),
        (answer, [{'text': 'Order count is COUNT(DISTINCT order_id).', 'mappings': [{'label': 'order count', 'field': 'order_id'}]},
                  {'text': 'Quantity sold is SUM(quantity).', 'mappings': [{'label': 'quantity sold', 'field': 'quantity'}]}]))
    assert len(ledger.requirements) == rows
    assert [m.aggregation for r in ledger.requirements[:2] for m in r.mappings] == ['count_distinct', 'sum']
    a = req.evaluate(snapshot, ledger, capabilities.Checker(capabilities.load_registry()))
    assert a.state == ('ready' if rows == 2 else 'blocked')
    assert [i.requirement for i in a.issues] == ([] if rows == 2 else [answer])


@pytest.mark.parametrize('date_field,rows', [('order_date', 1), ('ship_date', 2)])
def test_definition_grain_and_date_field_are_reconciled(date_field, rows):
    fields = {'revenue': 'FLOAT', 'order_date': 'DATE', 'ship_date': 'DATE'}
    answer = f'Sales trend is SUM(revenue) by month of {date_field}.'
    snapshot, ledger = merge_turns(fields, ('Show the sales trend', [{'text': 'Show the sales trend',
        'needs': [{'capability': 'chart.time_series', 'fields': {'date_field': 'order_date'}}],
        'mappings': [{'label': 'sales trend', 'field': None}]}]),
        (answer, [{'text': answer, 'mappings': [{'label': 'sales trend', 'field': 'revenue'}]}]))
    # Code reads the stated grain; a different date field is never absorbed into the old binding.
    assert len(ledger.requirements) == rows
    mapping = ledger.requirements[0].mappings[0]
    assert (mapping.field, mapping.aggregation, mapping.date_grain) == ('revenue', 'sum', 'month')
    a = req.evaluate(snapshot, ledger, capabilities.Checker(capabilities.load_registry()))
    assert a.state == ('ready' if rows == 1 else 'blocked')


@pytest.mark.parametrize('text,rows', [('That is everything; please plan the dashboard.', 0), ('Thanks!', 0),
                                       ('Thanks, and animate the map.', 1), ('Please plan it with GPS playback.', 1)])
def test_only_courtesy_needs_no_fail_closed_row(text, rows):
    _, ledger = merge_turns({'revenue': 'FLOAT'}, (text, []))
    assert len(ledger.requirements) == rows and list(ledger.processed_sources) == ['m0']


def test_removed_source_field_not_resurrected_by_old_spec(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    source(app, bid, revenue="FLOAT", region="STRING")
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "ready"
    with app.state.db.connect() as conn:
        conn.execute("UPDATE sources SET columns_json=? WHERE build_id=?", (json.dumps([{"name": "region", "type": "STRING"}]), bid))
    assert client.get(f"/api/builds/{bid}/feasibility").json()["state"] == "stale"
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any(i["status"] == "needs_data" and "revenue" in i["reason"] for i in a["issues"])


def test_view_pipeline_derived_fields_remain_available():
    snapshot = {"sources": [{"columns": [{"name": "sales", "type": "FLOAT"}]}], "definitions": {"derived-fields.md":
        '---\nview: p.d.view\nfields:\n- name: doubled\n  sql: sales * 2\n  type: FLOAT\n---\n'},
        "spec": {"datasource": {"table": "p.d.view", "fields": [{"name": "sales", "type": "FLOAT"}, {"name": "doubled", "type": "FLOAT"}]}}}
    assert req.schema(snapshot) == {"sales": "FLOAT", "doubled": "FLOAT"}
    snapshot["sources"][0]["columns"] = []
    assert req.schema(snapshot) == {}


def test_schema_uses_code_owned_normalization_and_physical_types(thin):
    client, app, bid, folder = thin
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", ("s_test", bid, "bigquery", "sales", "p.d.t", 10,
            json.dumps([{"name": "Order Total", "type": "number", "bq_type": "FLOAT"},
                        {"name": "OrderDate", "type": "string", "bq_type": "STRING", "date_like": True}])))
    assert req.schema(req.inputs(app.state.db, bid, folder)) == {"order_total": "FLOAT", "orderdate": "DATE"}


def test_missing_mapping_is_data_not_product_failure(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show latitude")
    use_model(monkeypatch, app, extracted(sid, mappings=[{"label": "Latitude", "field": "latitude"}]))
    _, a = check(client, app, bid)
    assert a["issues"][0]["status"] == "needs_data"


def test_unsupported_ledger_survives_supported_spec(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, "A bar chart and animate GPS points along a route")
    model = use_model(monkeypatch, app, extracted(sid), extracted(sid, "animation.temporal_playback", "Animate GPS points along a route"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any(i["status"] == "unsupported_app" for i in a["issues"])
    # Rechecking cannot strip the original unsupported requirement or call the model again.
    _, b = check(client, app, bid)
    assert b["state"] == "blocked" and len(req.load(folder).requirements) == 2 and model.calls == 1


def test_duplicate_descriptions_cannot_hide_an_unsupported_need(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "A bar chart and animated points")
    use_model(monkeypatch, app, extracted(sid), extracted(sid, "animation.temporal_playback"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unsupported_app"
    assert len(req.load(folder).requirements[0].needs) == 2


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('capability', ['animation.temporal_playback', None])
def test_clarification_keeps_merged_unsupported_or_unknown(thin, monkeypatch, reverse, capability):
    client, app, bid, folder = thin
    source(app, bid, gross_sales='FLOAT', net_sales='FLOAT')
    first = user(app, bid, 'Show Revenue')
    use_model(monkeypatch, app, extracted(first, mappings=[{'label': 'Revenue', 'field': None}]))
    assert check(client, app, bid)[1]['state'] == 'blocked'
    text = 'Revenue means net_sales. Animate GPS points.'
    sid = user(app, bid, text)
    rows = [extracted(sid, text=text, mappings=[{'label': 'Revenue', 'field': 'net_sales'}]),
            extracted(sid, text=text, needs=[{'capability': capability}] if capability else [])]
    use_model(monkeypatch, app, *(list(reversed(rows)) if reverse else rows))
    _, a = check(client, app, bid)
    assert a['state'] == 'blocked'
    assert any(i['status'] == ('unsupported_app' if capability else 'unknown') for i in a['issues'])
    ledger = req.load(folder)
    assert ledger.requirements[0].mappings[0].field == 'net_sales'
    merged = next(r for r in ledger.requirements if r.source.id == sid)
    assert any(n.capability == (capability or 'unknown.unclassified') for n in merged.needs)


def test_omitted_source_fails_closed(thin, monkeypatch):
    client, app, bid, folder = thin
    user(app, bid, "A requirement the model forgot")
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unknown"


@pytest.mark.parametrize("spoof", ["status", "resolution", "source_id"])
def test_model_cannot_grant_support_or_spoof_provenance(thin, monkeypatch, spoof):
    client, app, bid, folder = thin
    sid = user(app, bid, "Animate GPS points")
    item = extracted(sid, "animation.temporal_playback")
    item[spoof] = {"status": "supported", "resolution": "dropped", "source_id": "fake"}[spoof]
    model = use_model(monkeypatch, app, item)
    _, a = check(client, app, bid)
    assert a["state"] != "ready" and model.calls == 1 and not (folder / "requirements.json").exists()


def test_undeclared_animation_on_map_rejected(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    spec = json.loads((folder / "spec.json").read_text())
    spec["pages"][0]["components"][0].update(type="geo_map", options={"animate": True})
    (folder / "spec.json").write_text(json.dumps(spec))
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any("animate" in i["reason"] for i in a["issues"])


def test_reference_replacement_deletion_sticky_prototype_staleness(thin, monkeypatch):
    from dss.spec import references
    client, app, bid, folder = thin
    load(client, bid)
    use_model(monkeypatch, app)
    check(client, app, bid)
    monkeypatch.setattr(references, "decode", lambda _: None)
    vision = Capture(response=output(), requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: vision)
    def upload():
        response = client.post(f"/api/builds/{bid}/reference-images", data={"mode": "recreate"},
            files=[("files", ("a.png", png(), "image/png"))])
        assert response.status_code == 202
        client.portal.call(drain, app)
    upload()
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["id"] is None and a["prototype_stale"]
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "ready" and a["prototype_stale"]
    assert client.delete(f"/api/builds/{bid}/reference-images").status_code == 204
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["prototype_stale"]
    assert req.load(folder).invalidated
    assert "state: stale" in (folder / "docs/feasibility.md").read_text()


def test_reference_change_before_first_assessment(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    req.reference_changed(folder)
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["prototype_stale"]


def test_digest_covers_all_inputs(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    checker, ledger = capabilities.Checker(capabilities.load_registry()), req.Ledger()
    snapshot = req.inputs(app.state.db, bid, folder)
    before = req.input_digest(snapshot, ledger, checker)
    for key, value in (("reference", {"id": "ref_new"}), ("definitions", {"revenue": "net_sales"}),
                       ("sources", [{"columns": [{"name": "new", "type": "STRING"}]}]),
                       ("incoming", [{"id": "m_new", "text": "new request"}])):
        changed = copy.deepcopy(snapshot)
        changed[key] = value
        assert req.input_digest(changed, ledger, checker) != before
    changed = copy.deepcopy(snapshot)
    changed["spec"]["title"] = "new"
    assert req.input_digest(changed, ledger, checker) != before
    registry = checker.registry.model_copy(update={"registry_version": "1.1"})
    assert req.input_digest(snapshot, ledger, capabilities.Checker(registry)) != before
    assert req.input_digest(snapshot, ledger, capabilities.Checker(checker.registry, allowed={"bar"})) != before
    registry = checker.registry.model_dump(mode="json")
    registry["capabilities"][0]["label"] += "!"
    assert req.input_digest(snapshot, ledger, capabilities.Checker(capabilities.Registry.model_validate(registry))) != before


def test_spec_allowlist_and_schema_changes_get_stale_without_model(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    model = use_model(monkeypatch, app)
    check(client, app, bid)
    monkeypatch.setenv("DSS_ALLOWED_TYPES", "bar")
    assert client.get(f"/api/builds/{bid}/feasibility").json()["state"] == "stale"
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any(i["status"] == "unsupported_app" for i in a["issues"])
    source(app, bid, new="STRING")
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["prototype_stale"]
    assert model.calls == 0


class Counted(Capture):
    counted: int = 0
    reported: int = 24001

    async def count_request_tokens(self, request):
        self.counted += 1
        return self.reported


@pytest.mark.parametrize("reported,generated,state", [(24000, 1, "ready"), (24001, 0, "blocked")])
def test_full_counted_input_budget(thin, monkeypatch, reported, generated, state):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show bar chart")
    model = Counted(response=json.dumps({"requirements": [extracted(sid)]}), reported=reported, requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == state and model.calls == generated and model.counted == 1
    if state == "blocked":
        assert a["issues"][0]["reason"] == "Requirement check input 24,001 tokens, over its 24,000 budget"


def test_oversize_assembly_blocks_without_call(thin, monkeypatch):
    client, app, bid, folder = thin
    user(app, bid, "x" * 120000)
    model = use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and model.calls == 0
    reason = a["issues"][0]["reason"]
    assert reason.startswith("Requirement check input 3") and reason.endswith(" tokens, over its 24,000 budget")
    assert "x" * 20 not in reason


@pytest.mark.parametrize("count,state", [(40, "ready"), (41, "blocked")])
def test_requirement_count_bound(thin, monkeypatch, count, state):
    client, app, bid, folder = thin
    sid = user(app, bid, "Many bars")
    model = use_model(monkeypatch, app, *[extracted(sid, text=f"Bar {i}") for i in range(count)])
    _, a = check(client, app, bid)
    assert a["state"] == state and model.calls == 1
    assert len(req.load(folder).requirements) <= 40


def test_issue_count_overflow_blocks_whole_scope(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Many unknowns")
    use_model(monkeypatch, app, *[extracted(sid, "unknown.feature", text=f"Unknown {i}") for i in range(21)])
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and len(a["issues"]) == 1
    assert a["issues"][0]["reason"].startswith("21 active issues, over the 20-issue limit")
    assert len(req.load(folder).requirements) == 21


def test_failed_extraction_preserves_ledger_and_artifacts(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    use_model(monkeypatch, app)
    check(client, app, bid)
    user(app, bid, "new request")
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    model = FakeLLM(response="invalid JSON")
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == "stale" and model.calls == 1
    assert all(p.read_bytes() == content for p, content in before.items())


def test_save_rollback(thin, monkeypatch):
    client, app, bid, folder = thin
    use_model(monkeypatch, app)
    check(client, app, bid)
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    real = Path.replace
    def fail(path, target):
        if path.name == "requirements.json.tmp":
            raise OSError("injected")
        return real(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        req.save(folder, req.load(folder), req.Assessment(state="blocked"))
    assert all(p.read_bytes() == content for p, content in before.items())


def test_busy_stage_missing_and_empty_body(thin, monkeypatch):
    client, app, bid, folder = thin
    use_model(monkeypatch, app)
    assert client.get("/api/builds/b_000000000000/feasibility").status_code == 404
    assert client.post(f"/api/builds/{bid}/feasibility/check", json={}).status_code == 422
    app.state.harness.active_builds.add(bid)
    assert client.post(f"/api/builds/{bid}/feasibility/check").status_code == 409
    app.state.harness.active_builds.discard(bid)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='done' WHERE id=?", (bid,))
    assert client.post(f"/api/builds/{bid}/feasibility/check").status_code == 409


def test_deterministic_bounded_recompute_speed(record_property):
    checker = capabilities.Checker(capabilities.load_registry())
    ledger = req.Ledger(requirements=[req.Requirement(id=f"r{i}", source=req.Source(id="m", kind="message", text="bar"),
        text=f"Bar {i}", needs=[capabilities.Need(capability="chart.bar")]) for i in range(40)])
    snapshot = {"sources": [], "incoming": [], "reference": None, "definitions": {}, "spec": {
        "pages": [{"components": [{"id": f"c{i}", "type": "bar"} for i in range(24)]}]}}
    start = time.perf_counter()
    a = req.evaluate(snapshot, ledger, checker)
    elapsed = time.perf_counter() - start
    record_property('recompute_first_sample_s', elapsed)
    record_property('recompute_samples_s', json.dumps([elapsed]))
    assert a.state == "ready" and elapsed < .250


def test_bounded_recompute_speed_with_definitions(record_property):
    # Definition reconciliation scans every message for every label/field pair.
    cols = [{'name': f'c{i}', 'type': 'number', 'bq_type': 'FLOAT'} for i in range(28)]
    cols += [{'name': 'region', 'type': 'string', 'bq_type': 'STRING'}, {'name': 'order_date', 'type': 'date', 'bq_type': 'DATE'}]
    msgs = [req.Source(id=f'm{i}', kind='message', text=f'Metric {i} is SUM(c{i}), metric {i + 10} is SUM(c{i + 10}) and show them by region.')
            for i in range(10)]
    ledger = req.Ledger(requirements=[req.Requirement(id=f'r{i}', source=msgs[i % 10], text=f'Bar {i}',
        needs=[capabilities.Need(capability='chart.bar')], mappings=[req.Mapping(label=f'metric {i % 20}', field=f'c{i % 20}', aggregation='sum'),
        req.Mapping(label='region', field='region')]) for i in range(40)])
    snapshot = {'sources': [{'id': 's', 'table': 'p.d.t', 'columns': cols}], 'incoming': [m.model_dump() for m in msgs],
                'reference': None, 'definitions': {}, 'spec': {'pages': [{'components': [
                    {'id': f'k{i}', 'type': 'bar', 'dimensions': ['region'], 'metrics': [{'field': f'c{i}', 'agg': 'sum'}]} for i in range(24)]}]}}
    checker = capabilities.Checker(capabilities.load_registry())
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        req._reconcile_definitions(ledger, snapshot)
        req._reconcile_grains(ledger, snapshot)
        req.evaluate(snapshot, ledger, checker)
        timings.append(time.perf_counter() - start)
    record_property('recompute_first_sample_s', timings[0])
    record_property('recompute_samples_s', json.dumps(timings))
    assert min(timings) < .250, timings


RECREATE = json.loads((Path(__file__).parent / 'data/recreate_definitions.json').read_text(encoding='utf-8'))
NET = {'id': 'net_revenue', 'name': 'Net revenue', 'unit': 'USD', 'measure': {'field': 'revenue', 'agg': 'sum'}, 'ratio': None}
SALES = {'order_id': 'STRING', 'order_date': 'DATE', 'revenue': 'FLOAT', 'quantity': 'INTEGER', 'region': 'STRING'}


def recreate_snapshot(kpis=(NET,), instructions='', fields=SALES, items=None, rid='ref_obs'):
    """What inputs() returns for a recreate reference (task 18.2), without a database."""
    items = [{**item, 'id': f'o{n}'} for n, item in enumerate(items or RECREATE['items'], 1)]
    incoming = [req.Source(id=rid + ':instructions', kind='reference', text=instructions, reference_id=rid).model_dump()] * bool(instructions)
    incoming += [req.Source(id=f'{rid}:{i["id"]}', kind='image', text=json.dumps(i), reference_id=rid, image_id='img_obs',
                            item_id=i['id']).model_dump() for i in items if i['kind'] != 'decoration']
    return {'sources': [{'id': 's', 'table': 'p.d.t', 'columns': [{'name': n, 'type': t, 'bq_type': t} for n, t in fields.items()]}],
            'incoming': incoming, 'reference': {'id': rid, 'mode': 'recreate', 'instructions': instructions,
            'images': [{'id': 'img_obs'}], 'interpretation': {'items': items}}, 'definitions': {}, 'spec': None,
            'confirmed_kpis': [dict(k) for k in kpis]}


def recreate_assess(snapshot, extraction=None, ledger=None):
    extraction = extraction if extraction is not None else {**RECREATE['extraction']}
    rid = snapshot['reference']['id']
    # Only sources the extractor is sent (24.7: definition-only instructions are read by code).
    items = [{'source_id': f'{rid}:{oid}', **e} for oid, e in extraction.items()
             if f'{rid}:{oid}' in {s['id'] for s in req.new_sources(snapshot, ledger or req.Ledger())}]
    checker = capabilities.Checker(capabilities.load_registry())
    ledger = req.merge(ledger or req.Ledger(), snapshot, req.Extraction.model_validate({'requirements': items}))
    return ledger, req.evaluate(snapshot, ledger, checker, check_components=False)


def test_recreate_kpis_instructions_and_both_reconcile_without_dropping():
    """Release 2.5 b_b4319fb6113d: every observation stayed needs_clarification despite definitions."""
    unmatched = RECREATE['unmatched_kpis']
    for kpis, instructions in (((NET, {**NET, 'id': 'orders', 'name': 'Orders', 'unit': None, 'measure': {'field': 'order_id', 'agg': 'count_distinct'}},
                                 {**NET, 'id': 'units_sold', 'name': 'Units sold', 'unit': 'units', 'measure': {'field': 'quantity', 'agg': 'sum'}}), ''),
                               (unmatched, RECREATE['instructions']), ((NET,), RECREATE['instructions'])):
        snapshot = recreate_snapshot(kpis, instructions)
        ledger, a = recreate_assess(snapshot)
        assert a.state == 'ready', (instructions, [i.reason for i in a.issues])
        observed = [r for r in ledger.requirements if r.source.kind == 'image']
        assert sorted(r.source.item_id for r in observed) == ['o2', 'o3', 'o4', 'o5', 'o6']
        trend = next(r for r in observed if r.source.item_id == 'o5')
        assert trend.mappings == [req.Mapping(label='Revenue', field='revenue', unit='USD', aggregation='sum', date_grain='month')]
        # The definition-only instruction row is absorbed into the observations it clarifies.
        assert all(r.source.kind == 'image' for r in ledger.requirements)
        if instructions:
            assert all(snapshot['incoming'][0]['id'] in [s.id for s in r.clarifications] for r in observed)
        # Deterministic: a second pass on unchanged inputs is a fixed point.
        again = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
        assert again.requirements == ledger.requirements


GROSS = {'id': 'gross_revenue', 'name': 'Gross revenue', 'unit': 'USD', 'measure': {'field': 'gross_sales', 'agg': 'sum'}, 'ratio': None}
NET_SALES = {**GROSS, 'id': 'net_revenue', 'name': 'Net revenue', 'measure': {'field': 'net_sales', 'agg': 'sum'}}


@pytest.mark.parametrize('kpis, instructions, item, status, reason', [
    ((GROSS, NET_SALES), '', 'o2', 'needs_clarification', 'Clarify which confirmed KPI defines Revenue: Gross revenue, Net revenue'),
    (({**NET, 'measure': {'field': 'revenue', 'agg': 'avg'}},), '', 'o2', 'needs_clarification', 'screenshot shows sum but confirmed KPI Net revenue is avg'),
    (({**NET, 'id': 'orders', 'name': 'Orders', 'unit': None, 'measure': {'field': 'order_id', 'agg': 'count'}},), '', 'o3',
     'needs_clarification', 'screenshot shows count_distinct but confirmed KPI Orders is count'),
    (({**NET, 'unit': 'EUR'},), '', 'o2', 'needs_clarification', 'screenshot shows USD but confirmed KPI Net revenue is EUR'),
    ((NET,), 'Revenue = SUM(revenue) by week', 'o5', 'needs_clarification', 'Clarify the date grain for Revenue: month or week'),
    ((NET,), 'Revenue = AVG(revenue)', 'o2', 'needs_clarification', 'define Revenue differently (aggregation)'),
    ((NET,), 'Revenue = SUM(revenue). Revenue = AVG(revenue).', 'o2', 'needs_clarification', 'Conflicting definitions for Revenue'),
    ((), '', 'o2', 'needs_clarification', 'Define Revenue: confirm a matching Context KPI or add a reference instruction'),
    (({**NET, 'measure': {'field': 'net_revenue', 'agg': 'sum'}},), '', 'o2', 'needs_data', 'Field net_revenue is not in the connected data'),
])
def test_recreate_ambiguous_or_conflicting_definitions_stay_unresolved(kpis, instructions, item, status, reason):
    fields = {**SALES, 'gross_sales': 'FLOAT', 'net_sales': 'FLOAT'}
    ledger, a = recreate_assess(recreate_snapshot(kpis, instructions, fields))
    assert a.state == 'blocked'
    target = next(r for r in ledger.requirements if r.source.item_id == item)
    issues = [i for i in a.issues if i.requirement == target.text]
    assert any(i.status == status and reason in i.reason for i in issues), [(i.status, i.reason) for i in a.issues]
    assert all(i.alternatives == [] and i.resolution == 'unresolved' for i in issues)
    assert len([r for r in ledger.requirements if r.source.kind == 'image']) == 5  # nothing dropped
    if status == 'needs_clarification':
        assert 'observed:0' not in target.mapping_origins  # no authorization was recorded


def test_recreate_unsupported_flattened_and_ratio_observations_keep_their_paths():
    items = RECREATE['items'] + [
        {**RECREATE['items'][1], 'label': 'Flow', 'chart_candidate': 'sankey', 'metric_label': None, 'aggregation': None, 'unit': None},
        {**RECREATE['items'][1], 'label': 'Hero chart', 'metric_label': None, 'aggregation': None, 'unit': None},
        {**RECREATE['items'][1], 'label': 'Average order value', 'metric_label': 'Average order value', 'aggregation': None, 'unit': 'USD'}]
    extraction = {**RECREATE['extraction'],
                  'o7': {'text': 'Flow sankey', 'needs': [{'capability': 'chart.sankey'}]},
                  'o8': {'text': 'Hero chart as background art', 'needs': [{'capability': 'layout.background_image'}]},
                  'o9': {'text': 'Average order value scorecard', 'needs': [{'capability': 'chart.scorecard'}],
                         'mappings': [{'label': 'Average order value', 'unit': 'USD'}]}}
    ratio = {'id': 'avg_order_value', 'name': 'Average order value', 'unit': 'USD', 'measure': None,
             'ratio': {'numerator': 'net_revenue', 'denominator': 'orders'}}
    kpis = (NET, {**NET, 'id': 'orders', 'name': 'Orders', 'unit': None, 'measure': {'field': 'order_id', 'agg': 'count_distinct'}},
            {**NET, 'id': 'units_sold', 'name': 'Units sold', 'unit': None, 'measure': {'field': 'quantity', 'agg': 'sum'}}, ratio)
    ledger, a = recreate_assess(recreate_snapshot(kpis, items=items), extraction)
    by_item = {r.source.item_id: r for r in ledger.requirements if r.source.kind == 'image'}
    assert sorted(by_item) == ['o2', 'o3', 'o4', 'o5', 'o6', 'o7', 'o8', 'o9']
    status = {item: {i.status for i in a.issues if i.requirement == r.text} for item, r in by_item.items()}
    assert status['o7'] and status['o7'] <= {'unknown', 'unsupported_app', 'unsupported_product'}
    assert status['o8'] == {'needs_clarification'} and status['o9'] == {'needs_clarification'}
    assert not any(k.startswith('observed:') for k in by_item['o9'].mapping_origins)  # a ratio is never one metric
    assert all(not status[item] for item in ('o2', 'o3', 'o4', 'o5', 'o6')), status


def test_recreate_kpi_never_redefines_a_qualified_label_or_a_dimension():
    """Review 18.2: "Average revenue" is not "Revenue"; a KPI named for a region cannot rebind region."""
    items = [{**RECREATE['items'][1], 'label': 'Average revenue', 'metric_label': 'Average revenue', 'aggregation': None, 'unit': None},
             RECREATE['items'][5]]
    extraction = {'o1': {'text': 'Average revenue scorecard', 'needs': [{'capability': 'chart.scorecard'}],
                         'mappings': [{'label': 'Average revenue', 'field': 'revenue'}]},
                  'o2': RECREATE['extraction']['o6']}
    kpis = ({**NET, 'id': 'revenue', 'name': 'Revenue'}, {**NET, 'id': 'revenue_per_region', 'name': 'Revenue per region'})
    ledger, a = recreate_assess(recreate_snapshot(kpis, items=items), extraction)
    average, bar = (next(r for r in ledger.requirements if r.source.item_id == o) for o in ('o1', 'o2'))
    assert any('Define Average revenue' in i.reason for i in a.issues if i.requirement == average.text), a.issues
    assert bar.mappings[1] == req.Mapping(label='region', field='region')


def test_recreate_unsupported_observation_keeps_its_alternative_path():
    """Review 18.2: an observed GPS animation resolves through its code-built alternative, not a drop."""
    items = [{**RECREATE['items'][1], 'label': 'Route playback', 'chart_candidate': 'geo_map', 'metric_label': None, 'aggregation': None, 'unit': None}]
    extraction = {'o1': {'text': 'Animate GPS points along a route', 'needs': [{'capability': 'animation.temporal_playback'}]}}
    snapshot = recreate_snapshot(items=items)
    ledger, a = recreate_assess(snapshot, extraction)
    [issue] = [i for i in a.issues if i.resolution == 'unresolved']
    assert issue.status == 'unsupported_app' and issue.alternatives, a.issues
    ledger.assessment = a
    checker = capabilities.Checker(capabilities.load_registry())
    body = req.Decisions(assessment_id=a.id, decisions=[req.DecisionInput(issue_id=issue.id, action='accept_alternative',
                                                                          alternative_id=issue.alternatives[0].id)])
    _, decided = req.decide(snapshot, ledger, checker, body)
    assert decided.state == 'ready', decided.issues


def test_recreate_message_unit_conflict_is_not_overridden_by_a_kpi():
    """Review 18.2: a conversational EUR definition conflicts with a USD observation; a KPI cannot erase it."""
    snapshot = recreate_snapshot()
    message = req.Source(id='m_eur', kind='message', text='Revenue = SUM(revenue) in EUR').model_dump()
    snapshot['incoming'].insert(0, message)
    items = [{'source_id': f'ref_obs:{oid}', **RECREATE['extraction'][oid]} for oid in ('o2', 'o3', 'o4', 'o5', 'o6')]
    items.append({'source_id': 'm_eur', 'text': message['text'],
                  'mappings': [{'label': 'Revenue', 'field': 'revenue', 'unit': 'EUR', 'aggregation': 'sum'}]})
    ledger = req.merge(req.Ledger(), snapshot, req.Extraction.model_validate({'requirements': items}))
    a = req.evaluate(snapshot, ledger, capabilities.Checker(capabilities.load_registry()), check_components=False)
    scorecard = next(r for r in ledger.requirements if r.source.item_id == 'o2')
    assert any('incompatible units for Revenue' in i.reason for i in a.issues if i.requirement == scorecard.text), a.issues


def test_recreate_changed_or_draft_kpis_and_schema_invalidate_without_a_check():
    checker = capabilities.Checker(capabilities.load_registry())
    snapshot = recreate_snapshot(RECREATE['unmatched_kpis'] + [NET, {**NET, 'id': 'orders', 'name': 'Orders', 'unit': None,
        'measure': {'field': 'order_id', 'agg': 'count_distinct'}}, {**NET, 'id': 'units_sold', 'name': 'Units sold', 'unit': None,
        'measure': {'field': 'quantity', 'agg': 'sum'}}])
    ledger, a = recreate_assess(snapshot)
    assert a.state == 'ready', [i.reason for i in a.issues]
    for change in ('edit', 'draft'):
        changed = copy.deepcopy(snapshot)
        changed['confirmed_kpis'] = [{**k, 'measure': {'field': 'revenue', 'agg': 'avg'}} if k['id'] == 'net_revenue' else k
                                     for k in changed['confirmed_kpis']] if change == 'edit' else []
        # The stored reconciliation cannot authorize under new definitions before a check.
        stale = req.evaluate(changed, ledger, checker, check_components=False)
        assert stale.state == 'blocked' and any(i.id.startswith('obs_stale_') for i in stale.issues)
        rechecked, blocked = recreate_assess(changed, {}, ledger)
        assert blocked.state == 'blocked' and not any(i.id.startswith('obs_stale_') for i in blocked.issues)
        assert len([r for r in rechecked.requirements if r.source.kind == 'image']) == 5
        restored, ready = recreate_assess(snapshot, {}, rechecked)
        assert ready.state == 'ready' and restored.requirements == ledger.requirements
    narrowed = copy.deepcopy(snapshot)
    narrowed['sources'][0]['columns'] = [c for c in narrowed['sources'][0]['columns'] if c['name'] != 'revenue']
    _, missing = recreate_assess(narrowed, {}, ledger)
    assert any(i.status == 'needs_data' and 'revenue' in i.reason for i in missing.issues)


def test_recreate_bounded_recompute_speed(record_property):
    """24 observations (the interpretation maximum) reconcile with KPIs and instructions within 250 ms warm."""
    items = [{**RECREATE['items'][1 + n % 5], 'label': f'Chart {n}'} for n in range(24)]
    extraction = {f'o{n + 1}': RECREATE['extraction'][f'o{2 + n % 5}'] for n in range(24)}
    extraction['instructions'] = RECREATE['extraction']['instructions']
    snapshot = recreate_snapshot((NET,), RECREATE['instructions'], items=items)
    ledger, a = recreate_assess(snapshot, extraction)
    assert a.state == 'ready', [i.reason for i in a.issues]
    checker = capabilities.Checker(capabilities.load_registry())
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        req.evaluate(snapshot, ledger, checker, check_components=False)
        timings.append(time.perf_counter() - start)
    record_property('recompute_first_sample_s', timings[0])
    record_property('recompute_samples_s', json.dumps(timings))
    assert min(timings) < .250, timings


def test_ledger_mandatory_and_no_rows(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show bar")
    use_model(monkeypatch, app, extracted(sid))
    check(client, app, bid)
    section = requirement_sections(folder)[0]
    assert section.kind == "docs" and sid in section.body
    snapshot = req.inputs(app.state.db, bid, folder)
    assert not any(k in json.dumps(snapshot) for k in ("sample_rows", "api_key", "aggregate-cache"))


def test_only_mapped_unregistered_inputs_are_redundant():
    source = req.Source(id='m', kind='message', text='Compare regions')
    def row(fields, mappings):
        return req.Requirement(id='r', source=source, text='Compare regions', mappings=mappings,
                               needs=[capabilities.Need(capability='chart.bar', fields=fields)])
    mapped = req.Ledger(requirements=[row({'dimension': 'region'}, [req.Mapping(label='region', field='region')])])
    req._redundant_inputs(mapped)
    assert mapped.requirements[0].needs[0].fields == {}
    unmapped = req.Ledger(requirements=[row({'dimension': 'region'}, [])])
    req._redundant_inputs(unmapped)
    checker = capabilities.Checker(capabilities.load_registry())
    assert not checker.need(unmapped.requirements[0].needs[0], {'region': 'STRING'}).ok


def test_ledger_section_cites_each_source_once(tmp_path):
    # Retained definition provenance must not repeat whole messages per row (revise budget).
    text = 'Revenue is SUM(revenue), order count is COUNT(DISTINCT order_id). ' * 8
    first, answer = req.Source(id='m1', kind='message', text='Track revenue'), req.Source(id='m2', kind='message', text=text)
    rows = [req.Requirement(id=f'r{i}', source=first, text=f'Row {i}', clarifications=[answer],
                            mappings=[req.Mapping(label='revenue', field='revenue', aggregation='sum')],
                            mapping_origins={'0': 'x' * 64}) for i in range(6)]
    req.save(tmp_path, req.Ledger(requirements=rows), None)
    body = json.loads(requirement_sections(tmp_path)[0].body)
    assert body['sources'] == {'m1': {'kind': 'message', 'text': 'Track revenue'}, 'm2': {'kind': 'message', 'text': text}}
    assert all(r['source_id'] == 'm1' and r['clarification_source_ids'] == ['m2'] and 'mapping_origins' not in r
               for r in body['requirements'])
    assert requirement_sections(tmp_path)[0].body.count('order count is') == 8


def test_comment_and_image_item_provenance_and_reference_removal(thin):
    client, app, bid, folder = thin
    folder.mkdir(parents=True)
    message = episodic.save(app.state.db, bid, "user", json.dumps([{"component_id": "p1_revenue", "text": "Use a bar"}]), "revise")
    record = {"id": "ref_one", "mode": "recreate", "instructions": "", "images": [{"id": "img_one"}],
              "interpretation": {"items": [{"id": "o1", "kind": "chart", "chart_candidate": "sankey", "label": "Flow"}]}}
    (folder / "references.json").write_text(json.dumps(record))
    snapshot = req.inputs(app.state.db, bid, folder)
    comment, image = snapshot["incoming"]
    assert comment["kind"] == "comment" and comment["id"] == message["id"] + ":0" and comment["component_id"] == "p1_revenue"
    assert image["kind"] == "image" and image["reference_id"] == "ref_one" and image["image_id"] == "img_one" and image["item_id"] == "o1"
    ledger = req.merge(req.Ledger(), snapshot, req.Extraction(requirements=[
        req.Extracted(**extracted(comment["id"])), req.Extracted(source_id=image["id"], text="Flow with sankey")]))
    assert len(ledger.requirements) == 2
    snapshot["reference"] = None
    snapshot["incoming"] = [comment]
    updated = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    assert len(updated.requirements) == 1 and updated.requirements[0].source.kind == "comment"


def test_revise_keeps_ledger_as_mandatory_docs(thin, monkeypatch):
    from dss.harness.context import revise_context
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, "Show bar chart")
    use_model(monkeypatch, app, extracted(sid))
    check(client, app, bid)
    config = app.state.settings.get()
    document = json.loads((folder / "spec.json").read_text())
    for context in (revise_context(document, [{"component_id": "p1_revenue", "text": "Blue"}], {"scorecard"}, config, folder=folder),):
        sections = [s for s in context.sections if s.name == "requirements.json"]
        assert len(sections) == 1 and sections[0].kind == "docs" and sid in sections[0].text
        assert sid in context.refit(lambda text: True)  # Mandatory even when all droppable memory is removed.


def choose(client, bid, assessment, *items):
    return client.post(f"/api/builds/{bid}/feasibility/decisions", json={"assessment_id": assessment["id"], "decisions": list(items)})


def drop(issue):
    return {"issue_id": issue["id"], "action": "drop", "alternative_id": None}


def accept(issue):
    return {"issue_id": issue["id"], "action": "accept_alternative", "alternative_id": issue["alternatives"][0]["id"]}


def animated(thin, monkeypatch, *, with_spec=False):
    client, app, bid, folder = thin
    if with_spec:
        load(client, bid)
    source(app, bid, observed_at="DATE", revenue="FLOAT", region="STRING")
    sid = user(app, bid, "Animate GPS points along a route")
    use_model(monkeypatch, app, extracted(sid, "animation.temporal_playback", "Animate GPS points along a route",
                                         component_ids=["p1_revenue"]))
    return check(client, app, bid)[1]


def test_accept_is_explicit_durable_and_does_no_work(thin, monkeypatch):
    client, app, bid, folder = thin
    a = animated(thin, monkeypatch, with_spec=True)
    assert a["state"] == "blocked" and a["issues"][0]["alternatives"]
    assert "observed_at" in a["issues"][0]["alternatives"][0]["label"]
    before = {p: p.read_bytes() for p in folder.iterdir() if p.is_file() and p.name != "requirements.json"}
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT count(*) FROM traces").fetchone()[0]
    response = choose(client, bid, a, accept(a["issues"][0]))
    assert response.status_code == 200, response.text
    b = response.json()
    assert b["state"] == "ready" and b["id"] != a["id"]
    assert b["issues"][0]["resolution"] == "accepted_alternative"
    assert client.get(f"/api/builds/{bid}/feasibility").json() == b
    assert all(p.read_bytes() == value for p, value in before.items()) and not app.state.engine_tasks
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM traces").fetchone()[0] == traces
    d = req.load(folder).decisions[0]
    assert d["requirement_id"] and d["meaning"] and d["prerequisites"] and d["evidence"]
    assert d["alternative"]["needs"][0]["fields"] == {"date_field": "observed_at"}
    assert choose(client, bid, a, drop(a["issues"][0])).json()["error"]["code"] == "feasibility_stale"
    _, b = check(client, app, bid)
    assert b["state"] == "ready" and b["issues"][0]["resolution"] == "accepted_alternative"


def test_existing_choices_survive_optional_clarification_provenance(thin, monkeypatch):
    client, app, bid, folder = thin
    a = animated(thin, monkeypatch)
    assert choose(client, bid, a, accept(a['issues'][0])).status_code == 200
    ledger = req.load(folder)
    original = ledger.requirements[0]
    # The exact meaning shape written by 11.4 before clarifications existed.
    ledger.decisions[0]['meaning'] = req.digest(original.model_dump(exclude={'resolution', 'clarifications', 'properties', 'superseded', 'mapping_origins', 'mapping_conflicts'}))
    snapshot = req.inputs(app.state.db, bid, folder)
    a = req.evaluate(snapshot, ledger, capabilities.Checker(capabilities.load_registry()))
    assert a.state == 'ready' and a.issues[0].resolution == 'accepted_alternative'


def test_choice_survives_spec_and_registry_but_rechecks_mapping_and_data(thin, monkeypatch):
    client, app, bid, folder = thin
    a = animated(thin, monkeypatch, with_spec=True)
    assert choose(client, bid, a, accept(a["issues"][0])).status_code == 200
    spec = json.loads((folder / "spec.json").read_text())
    component = spec["pages"][0]["components"][0]
    assert component["id"] == "p1_revenue"
    component.update(type="time_series", date_dimension="observed_at")
    (folder / "spec.json").write_text(json.dumps(spec))
    registry = capabilities.load_registry().model_dump(mode="json")
    registry["registry_version"] = "1.1"
    registry["capabilities"][1]["label"] += " updated documentation"
    updated = capabilities.Registry.model_validate(registry)
    monkeypatch.setattr("dss.harness.nodes.capability_check.load_registry", lambda: updated)
    monkeypatch.setattr("dss.api.feasibility.load_registry", lambda: updated)
    assert client.get(f"/api/builds/{bid}/feasibility").json()["state"] == "stale"
    _, b = check(client, app, bid)
    assert b["state"] == "ready" and b["issues"][0]["resolution"] == "accepted_alternative"
    component["date_dimension"] = "region"
    (folder / "spec.json").write_text(json.dumps(spec))
    _, b = check(client, app, bid)
    assert b["state"] == "blocked" and b["issues"][0]["resolution"] == "unresolved"
    # A fresh explicit choice permits repair of the old mapping, but does not publish it.
    response = choose(client, bid, b, accept(b["issues"][0]))
    assert response.status_code == 200 and response.json()["state"] == "ready" and response.json()["prototype_stale"]
    component["date_dimension"] = "observed_at"
    (folder / "spec.json").write_text(json.dumps(spec))
    _, b = check(client, app, bid)
    assert b["state"] == "ready" and req.load(folder).decisions[0]["applied"]
    component["date_dimension"] = "region"
    (folder / "spec.json").write_text(json.dumps(spec))
    _, b = check(client, app, bid)
    assert b["state"] == "blocked"  # Even returning to the originally authorized old prototype needs a new choice.
    component["date_dimension"] = "observed_at"
    (folder / "spec.json").write_text(json.dumps(spec))
    with app.state.db.connect() as conn:
        conn.execute("UPDATE sources SET columns_json=? WHERE build_id=?", (json.dumps([
            {"name": "observed_at", "type": "STRING"}, {"name": "revenue", "type": "FLOAT"}, {"name": "region", "type": "STRING"}]), bid))
    _, b = check(client, app, bid)
    assert b["state"] == "blocked" and not b["issues"][0]["alternatives"]


def test_requirement_meaning_and_allowlist_revoke_choice(thin, monkeypatch):
    client, app, bid, folder = thin
    a = animated(thin, monkeypatch)
    choose(client, bid, a, accept(a["issues"][0]))
    ledger = req.load(folder)
    snapshot = req.inputs(app.state.db, bid, folder)
    checker = capabilities.Checker(capabilities.load_registry())
    changed = ledger.model_copy(deep=True)
    changed.requirements[0].mappings = [req.Mapping(label="Revenue", field="revenue")]
    assert req.evaluate(snapshot, changed, checker).state == "blocked"
    narrowed = capabilities.Checker(checker.registry, allowed={"bar"})
    assert req.evaluate(snapshot, ledger, narrowed).state == "blocked"
    changed = copy.deepcopy(snapshot)
    changed["sources"][0]["table"] = "p.d.replacement"
    assert req.evaluate(changed, ledger, checker).state == "blocked"
    registry = checker.registry.model_dump(mode="json")
    cap = next(c for c in registry["capabilities"] if c["id"] == "chart.time_series")
    cap["app"]["status"] = "unsupported"
    assert req.evaluate(snapshot, ledger, capabilities.Checker(capabilities.Registry.model_validate(registry))).state == "blocked"


def test_no_unsupported_or_inferred_alternative(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Animate GPS points")
    source(app, bid, latitude="FLOAT", longitude="FLOAT", date_text="STRING")
    use_model(monkeypatch, app, extracted(sid, "animation.temporal_playback"))
    _, a = check(client, app, bid)
    assert a["issues"][0]["alternatives"] == []
    assert a["state"] == "blocked"


@pytest.mark.parametrize("items", [[], ["duplicate"], ["missing"], ["drop_with_id"], ["accept_null"], ["accept_fake"], ["too_many"]])
def test_decision_validation_is_atomic(thin, monkeypatch, items):
    client, app, bid, folder = thin
    a = animated(thin, monkeypatch)
    valid = drop(a["issues"][0])
    case = items[0] if items else "empty"
    bad = {**valid, "issue_id": "unknown"}
    body = {
        "empty": [], "duplicate": [valid, valid], "missing": [valid, bad],
        "drop_with_id": [{**valid, "alternative_id": "unexpected"}],
        "accept_null": [{**valid, "action": "accept_alternative"}],
        "accept_fake": [{**valid, "action": "accept_alternative", "alternative_id": "fake"}],
        "too_many": [{**valid, "issue_id": str(i)} for i in range(21)]}[case]
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    result = choose(client, bid, a, *body)
    assert result.status_code == 422, result.text
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not app.state.harness.active_builds


def test_twenty_distinct_decisions_and_no_implicit_consent(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Twenty explicit unsupported behaviors")
    use_model(monkeypatch, app, *(extracted(sid, f"unknown.feature_{i}", text=f"Feature {i}") for i in range(20)))
    _, a = check(client, app, bid)
    assert len(a["issues"]) == 20
    response = choose(client, bid, a, *(drop(i) for i in a["issues"][:-1]))
    assert response.status_code == 200 and response.json()["state"] == "blocked"
    a = response.json()
    assert sum(i["resolution"] == "unresolved" for i in a["issues"]) == 1
    # One atomic request may carry the maximum 20 choices on a fresh assessment.
    ledger = req.load(folder)
    ledger.decisions = []
    snapshot, checker = req.inputs(app.state.db, bid, folder), capabilities.Checker(capabilities.load_registry())
    req.save(folder, ledger, req.evaluate(snapshot, ledger, checker))
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    response = choose(client, bid, a, *(drop(i) for i in a["issues"]))
    assert response.status_code == 200 and response.json()["state"] == "ready"


def pending(thin, comments, ledger=None):
    """Exercise the persistence interface that comments/revise will call in 11.7."""
    client, app, bid, folder = thin
    snapshot = req.inputs(app.state.db, bid, folder)
    ledger = req.stage_comments(ledger or req.load(folder), comments)
    sources = req.new_sources(snapshot, ledger)
    extraction = req.Extraction(requirements=[req.Extracted(**extracted(s["id"], "animation.temporal_playback", s["text"],
        component_ids=[s["component_id"]] if s.get("component_id") else [])) for s in sources])
    ledger = req.merge(ledger, snapshot, extraction)
    checker = capabilities.Checker(capabilities.load_registry())
    ledger.verification = req.verification(snapshot, ledger, checker)
    a = req.evaluate(snapshot, ledger, checker)
    req.save(folder, ledger, a)
    return a.model_dump()


def test_pending_reload_reapply_ids_replace_and_abandon(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    a = animated(thin, monkeypatch)
    # Keep an unrelated requirement and its durable decision.
    choose(client, bid, a, drop(a["issues"][0]))
    original = req.load(folder).requirements[0].id
    comments = [{"component_id": "p1_revenue", "text": "Animate this first"},
                {"component_id": "p1_revenue", "text": "Then animate this second"}]
    a = pending(thin, comments)
    assert a["state"] == "blocked" and a["prototype_stale"]
    assert a == client.get(f"/api/builds/{bid}/feasibility").json()
    batch = a["pending_comments"]
    assert batch["comments"] == comments
    assert {r.source.batch_id for r in req.load(folder).requirements if r.id != original} == {batch["id"]}
    # A recovery check must not turn the batch-only stale reason into a sticky global one.
    _, a = check(client, app, bid)
    assert a["prototype_stale"] and not req.load(folder).prototype_stale
    url = f"/api/builds/{bid}/feasibility/reapply"
    for assessment_id, batch_id in (("old", batch["id"]), (a["id"], "old")):
        result = client.post(url, json={"assessment_id": assessment_id, "batch_id": batch_id})
        assert result.status_code == 409 and result.json()["error"]["code"] == "feasibility_stale"
    assert client.post(url, json={"assessment_id": a["id"], "batch_id": batch["id"]}).json()["error"]["code"] == "feasibility_blocked"
    b = choose(client, bid, a, *(drop(i) for i in a["issues"] if i["resolution"] == "unresolved")).json()
    assert b["state"] == "ready" and b["prototype_stale"]
    assert client.post(url, json={"assessment_id": a["id"], "batch_id": batch["id"]}).json()["error"]["code"] == "feasibility_stale"
    # Validation returns the ordered batch without applying it; 11.7 wires the revise action.
    snapshot, ledger = req.inputs(app.state.db, bid, folder), req.load(folder)
    assert req.validate_reapply(snapshot, ledger, capabilities.Checker(capabilities.load_registry()),
        req.Reapply(assessment_id=b["id"], batch_id=batch["id"])).comments == req.PendingComments.model_validate(batch).comments
    new = pending(thin, [{"component_id": "p1_revenue", "text": "A different request"}])
    assert new["pending_comments"]["id"] != batch["id"] and new["state"] == "blocked"
    assert len(req.load(folder).decisions) == 1  # Only the unrelated choice remains.
    assert client.post(url, json={"assessment_id": new["id"], "batch_id": batch["id"]}).json()["error"]["code"] == "feasibility_stale"
    before = (folder / "spec.json").read_bytes()
    assert client.delete(f"/api/builds/{bid}/feasibility/pending-comments", params={"assessment_id": b["id"]}).json()["error"]["code"] == "feasibility_stale"
    response = client.delete(f"/api/builds/{bid}/feasibility/pending-comments", params={"assessment_id": new["id"]})
    assert response.status_code == 200, response.text
    c = response.json()
    assert c["pending_comments"] is None and c["state"] == "ready" and not c["prototype_stale"]
    assert [r.id for r in req.load(folder).requirements] == [original]
    assert len(req.load(folder).decisions) == 1 and (folder / "spec.json").read_bytes() == before
    _, c = check(client, app, bid)
    assert c["state"] == "ready" and c["pending_comments"] is None and not c["prototype_stale"]


def test_abandon_keeps_other_issues_and_reference_staleness(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, "Unknown original request")
    use_model(monkeypatch, app, extracted(sid, "unknown.behavior"))
    check(client, app, bid)
    ledger = req.load(folder)
    ledger.prototype_stale = True  # An independent reference/spec stale reason.
    a = pending(thin, [{"component_id": "p1_revenue", "text": "Animate"}], ledger)
    result = client.delete(f"/api/builds/{bid}/feasibility/pending-comments", params={"assessment_id": a["id"]})
    assert result.status_code == 200
    assert result.json()["state"] == "blocked" and result.json()["prototype_stale"]
    assert len(result.json()["issues"]) == 1 and len(req.load(folder).requirements) == 1


def test_decisions_lock_and_write_failure_rollback(thin, monkeypatch):
    client, app, bid, folder = thin
    a = animated(thin, monkeypatch)
    app.state.harness.active_builds.add(bid)
    assert choose(client, bid, a, drop(a["issues"][0])).json()["error"]["code"] == "wrong_stage"
    app.state.harness.active_builds.discard(bid)
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    real = Path.replace
    def fail(path, target):
        if path.name == "requirements.json.tmp":
            raise OSError("injected decision save failure")
        return real(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="injected decision"):
        choose(client, bid, a, drop(a["issues"][0]))
    assert all(p.read_bytes() == value for p, value in before.items()) and not app.state.harness.active_builds


def test_legacy_choice_is_bound_to_data_origin(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    spec = json.loads((folder / "spec.json").read_text())
    spec["datasource"]["fields"].append({"name": "observed_at", "type": "DATE", "label": "Observed at", "role": "dimension"})
    (folder / "spec.json").write_text(json.dumps(spec))
    sid = user(app, bid, "Animate GPS points")
    use_model(monkeypatch, app, extracted(sid, "animation.temporal_playback"))
    _, a = check(client, app, bid)
    assert choose(client, bid, a, accept(a["issues"][0])).json()["state"] == "ready"
    spec["datasource"]["table"] = "p.d.another_table"
    (folder / "spec.json").write_text(json.dumps(spec))
    _, b = check(client, app, bid)
    assert b["state"] == "blocked" and b["issues"][0]["resolution"] == "unresolved"


def test_abandon_accepted_pending_alternative_clears_only_batch_staleness(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    source(app, bid, observed_at="DATE", revenue="FLOAT", region="STRING")
    a = pending(thin, [{"component_id": "p1_revenue", "text": "Animate this"}])
    b = choose(client, bid, a, accept(a["issues"][0]))
    assert b.status_code == 200 and b.json()["state"] == "ready" and b.json()["prototype_stale"]
    assert not req.load(folder).prototype_stale
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert not req.load(folder).prototype_stale
    result = client.delete(f"/api/builds/{bid}/feasibility/pending-comments", params={"assessment_id": a["id"]})
    assert result.status_code == 200 and result.json()["state"] == "ready" and not result.json()["prototype_stale"]


def test_abandon_clears_only_batch_owned_scope_failure():
    ledger = req.stage_comments(req.Ledger(), [{'component_id': 'p1_revenue', 'text': 'A large request'}])
    ledger.scope_error = 'Reduce scope'
    assert req.abandon_pending(ledger).scope_error == 'Reduce scope'
    ledger.scope_batch_id = ledger.pending_comments.id
    assert req.abandon_pending(ledger).scope_error is None


def test_static_map_alternative_checks_inherited_type_and_binding():
    checker = capabilities.Checker(capabilities.load_registry())
    snapshot = {"sources": [], "incoming": [], "reference": None, "definitions": {}, "spec": {
        "datasource": {"table": "p.d.view", "fields": [{"name": "country", "type": "GEO"}]},
        "pages": [{"components": [{"id": "p1_map", "type": "geo_map", "dimensions": ["country"],
                                     "options": {"geo_type": "country"}}]}]}}
    ledger = req.Ledger(requirements=[req.Requirement(id="r1", source=req.Source(id="m", kind="message", text="Animate GPS"),
        text="Animate GPS", component_ids=["p1_map"], needs=[capabilities.Need(capability="animation.temporal_playback")])])
    a = req.evaluate(snapshot, ledger, checker)
    assert len(a.issues[0].alternatives) == 1 and "Static country" in a.issues[0].alternatives[0].label
    ledger.assessment = a
    ledger, b = req.decide(snapshot, ledger, checker, req.Decisions(assessment_id=a.id,
        decisions=[req.DecisionInput(**accept(a.issues[0].model_dump()))]))
    assert b.state == "ready" and ledger.decisions[0]["applied"]
    snapshot["spec"]["pages"][0]["components"][0]["options"]["geo_type"] = "city"
    assert req.evaluate(snapshot, ledger, checker).state == "blocked"


def test_decision_recompute_budget(record_property):
    checker = capabilities.Checker(capabilities.load_registry())
    snapshot = {"sources": [], "incoming": [], "reference": None, "definitions": {}, "spec": {
        "datasource": {"table": "p.d.view", "fields": [{"name": "observed_at", "type": "DATE"}]},
        "pages": [{"components": [{"id": f"c{i}", "type": "time_series", "date_dimension": "observed_at"} for i in range(24)]}]}}
    ledger = req.Ledger(requirements=[req.Requirement(id=f"r{i}", source=req.Source(id="m", kind="message", text="Animate"),
        text=f"Animate {i}", component_ids=[f"c{i % 24}"],
        needs=[capabilities.Need(capability="animation.temporal_playback" if i < 20 else "chart.bar")]) for i in range(40)])
    a = req.evaluate(snapshot, ledger, checker)
    ledger.assessment = a
    body = req.Decisions(assessment_id=a.id, decisions=[req.DecisionInput(**accept(i.model_dump())) for i in a.issues])
    ledger, _ = req.decide(snapshot, ledger, checker, body)
    started = time.perf_counter()
    a = req.evaluate(snapshot, ledger, checker)
    elapsed = time.perf_counter() - started
    record_property('recompute_first_sample_s', elapsed)
    record_property('recompute_samples_s', json.dumps([elapsed]))
    assert a.state == "ready" and elapsed < .250


def staged_snapshot(pages, questions):
    """A connected sales source, the shape fixtures and a staged Blueprint, before layout (16.1)."""
    from test_blueprint import fixture
    from test_render import staged_rows
    from dss.data.bigquery import prepare_csv
    _, columns, _ = prepare_csv(Path('tests/data/interview_sales.csv').read_bytes())
    context = fixture('context')
    context.update(datasets=[{'source_id': 'sales', 'summary': 'Sales'}], derived_fields=[])
    outline, rows = staged_rows(pages, questions)
    blueprint = fixture('blueprint')
    blueprint.update(view_sources={'base': 'sales', 'joins': [], 'union': []}, derived_fields=[], rows=rows)
    return {'sources': [{'id': 'sales', 'table': 'p.d.sales', 'columns': [
        {'name': c.name, 'type': c.field_type, 'bq_type': c.field_type} for c in columns]}],
        'context': context, 'outline': outline, 'design': fixture('design'), 'blueprint': blueprint,
        'incoming': [], 'reference': None, 'definitions': {}, 'spec': None}


def laid_out(snapshot):
    from dss.artifacts.models import Blueprint, Design, Outline
    from dss.harness.nodes import view
    from dss.spec.auto_layout import layout
    blueprint = Blueprint.model_validate(snapshot['blueprint'])
    fields = view.blueprint_fields(snapshot['sources'], blueprint.view_sources, [])
    return layout(blueprint, Design.model_validate(snapshot['design']), Outline.model_validate(snapshot['outline']),
                  fields, build_id='b_123456789abc', archetype='executive').model_dump(mode='json')


@pytest.mark.parametrize('pages,questions', [(3, 3), (5, 4)])
def test_staged_scope_is_ready_before_and_after_layout(pages, questions):
    """No total-component ceiling: 27 and 60 laid-out components stay ready (final re-audit 16.1)."""
    checker = capabilities.Checker(capabilities.load_registry())
    snapshot = staged_snapshot(pages, questions)
    before = req.evaluate(snapshot, req.Ledger(), checker)
    assert before.state == 'ready', before.issues
    snapshot['spec'] = laid_out(snapshot)
    assert [len(p['components']) for p in snapshot['spec']['pages']] == [3 * questions] * pages
    after = req.evaluate(snapshot, req.Ledger(), checker)
    assert after.state == 'ready' and after.issues == [], after.issues
    assert req.coverage_errors(snapshot, req.Ledger(), checker) == []


def thirteen_on_one_page(bp):
    bp['rows'][9:13] = [{**r, 'page': 1, 'section_id': 's1'} for r in bp['rows'][9:13]]


def unknown_field(bp):
    bp['rows'][4]['component']['dimensions'] = ['missing_field']


def wrong_kpi(bp):
    bp['rows'][0]['component']['metrics'] = [{'field': 'revenue', 'agg': 'avg'}]


def unsupported_option(bp):
    bp['rows'][1]['component']['options'] = {'animate': True}


@pytest.mark.parametrize('change,reason', [
    (thirteen_on_one_page, 'Too many components'),
    (lambda bp: bp['rows'][-1].update(page=6), 'Blueprint needs 1-5 pages'),
    (unknown_field, 'missing_field'),
    (wrong_kpi, 'confirmed field and aggregation'),
    (unsupported_option, 'Option animate')])
def test_staged_scope_keeps_row_page_field_kpi_and_capability_checks(change, reason):
    checker = capabilities.Checker(capabilities.load_registry())
    snapshot = staged_snapshot(3, 3)
    change(snapshot['blueprint'])
    assessment = req.evaluate(snapshot, req.Ledger(), checker)
    assert assessment.state == 'blocked'
    assert any(reason in i.reason and i.resolution == 'unresolved' for i in assessment.issues), assessment.issues


from test_blueprint import blueprint_api  # noqa: E402,F401  (fixture)
from test_context_node import context_api  # noqa: E402,F401  (fixture)
from test_render import staged_flow  # noqa: E402,F401  (fixture)


def select(client, bid, selected):
    response = client.put(f'/api/builds/{bid}/outline/selection', json={'questions': [{'id': 'q1_2', 'selected': selected}]})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('staged_flow', [(1, 2)], indirect=True)
def test_outline_requirement_change_recovers_only_by_explicit_replan(staged_flow, blueprint_api, monkeypatch):
    """18.1: a changed supported outline requirement invalidates the accepted prototype; restoring it does not re-authorize."""
    from test_context_node import wait
    from test_render import executes, feasibility_check, execution_blocked, published_proof
    client, app, bid, folder, bq, _ = staged_flow
    *_, llm, value = blueprint_api
    select(client, bid, False)
    a = client.get(f'/api/builds/{bid}/feasibility').json()
    assert a['state'] == 'stale' and a['prototype_stale']
    execution_blocked(client, bid, 'wrong_stage')
    assert feasibility_check(client, app, bid)['prototype_stale']
    select(client, bid, True)
    restored = feasibility_check(client, app, bid)
    assert restored['state'] == 'ready' and restored['prototype_stale'] and req.load(folder).prototype_stale
    select(client, bid, False)
    assert client.post(f'/api/builds/{bid}/outline/confirm').status_code == 200
    llm.replies.append(json.dumps(value))
    assert client.post(f'/api/builds/{bid}/design/confirm').status_code == 202
    wait(app)
    accepted = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(app)
    fresh = client.get(f'/api/builds/{bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    assert fresh['id'] == published_proof(folder)
    spec = json.loads((folder / 'spec.json').read_text(encoding='utf-8'))
    assert not any('1.2' in c['label'] for p in spec['pages'] for c in p['components'])
    executes(client, app, bid, monkeypatch)


@pytest.mark.parametrize('staged_flow', [(1, 1)], indirect=True)
def test_allowlist_narrowing_and_restoration_need_explicit_replan(staged_flow, blueprint_api, monkeypatch):
    from test_render import executes, feasibility_check, execution_blocked, published_proof, replan, reloaded
    client, app, bid, folder, bq, _ = staged_flow
    *_, llm, value = blueprint_api
    monkeypatch.setenv('DSS_ALLOWED_TYPES', 'scorecard')
    assert client.get(f'/api/builds/{bid}/feasibility').json()['prototype_stale']
    execution_blocked(client, bid)
    narrowed = feasibility_check(client, app, bid)
    assert narrowed['state'] == 'blocked' and narrowed['prototype_stale']
    assert any(i['status'] == 'unsupported_app' for i in narrowed['issues'])
    monkeypatch.delenv('DSS_ALLOWED_TYPES')
    # Restoration plus GET/check proves support again, never the old artifact.
    assert client.get(f'/api/builds/{bid}/feasibility').json()['prototype_stale']
    restored = feasibility_check(client, app, bid)
    assert restored['state'] == 'ready' and restored['prototype_stale']
    assert feasibility_check(client, app, bid)['prototype_stale']
    execution_blocked(client, bid)
    assert replan(client, app, bid, llm, value, monkeypatch)['status'] == 'ok'
    fresh = client.get(f'/api/builds/{bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'] and fresh['id'] == published_proof(folder)
    executes(client, app, bid, monkeypatch)
    assessment, build = reloaded(app, bid)
    assert assessment['id'] == fresh['id'] and not assessment['prototype_stale'] and build['stage'] == 'done'


@pytest.mark.parametrize('staged_flow', [(1, 1)], indirect=True)
def test_replan_keeps_pending_comment_gate(staged_flow, blueprint_api, monkeypatch):
    """Replanning never silently applies, clears or authorizes a pending batch; its abandon flow still decides."""
    from test_render import (executes, execution_blocked, feasibility_check, published_proof, replan,
                             upload_style, use_reference_model)
    client, app, bid, folder, bq, _ = staged_flow
    *_, llm, value = blueprint_api
    use_reference_model(app, monkeypatch)
    upload_style(client, app, bid)
    feasibility_check(client, app, bid)
    target = json.loads((folder / 'spec.json').read_text(encoding='utf-8'))['pages'][0]['components'][0]['id']
    a = pending((client, app, bid, folder), [{'component_id': target, 'text': 'Animate this'}])
    assert a['state'] == 'blocked' and a['prototype_stale'] and a['pending_comments']
    batch = a['pending_comments']['id']
    llm.replies.append(json.dumps(value))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    assert client.post(f'/api/builds/{bid}/blueprint/regenerate').status_code == 202
    from test_context_node import wait
    wait(app)
    refused = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked', refused.text
    kept = client.get(f'/api/builds/{bid}/feasibility').json()
    assert kept['pending_comments']['id'] == batch and kept['prototype_stale'] and req.load(folder).prototype_stale
    # Resolved batch: the replan publishes, clears the artifact flag, yet keeps the batch and its gate.
    resolved = choose(client, bid, kept, *(drop(i) for i in kept['issues'] if i['resolution'] == 'unresolved'))
    assert resolved.status_code == 200 and resolved.json()['state'] == 'ready', resolved.text
    assert replan(client, app, bid, llm, value, monkeypatch)['status'] == 'ok'
    gated = client.get(f'/api/builds/{bid}/feasibility').json()
    assert gated['pending_comments']['id'] == batch and gated['prototype_stale'] and not req.load(folder).prototype_stale
    execution_blocked(client, bid)
    abandoned = client.delete(f'/api/builds/{bid}/feasibility/pending-comments', params={'assessment_id': gated['id']})
    assert abandoned.status_code == 200, abandoned.text
    assert abandoned.json()['pending_comments'] is None and not abandoned.json()['prototype_stale']
    fresh = client.get(f'/api/builds/{bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'] and fresh['id'] == published_proof(folder)
    executes(client, app, bid, monkeypatch)


@pytest.mark.parametrize("component_id,status", [("p1_revenue", "unsupported_app"), ("p1_regions", None)])
def test_color_need_on_scorecard_fails_fast_per_chart_type(thin, monkeypatch, component_id, status):
    """19.4: scorecards get no set_style, so a color need bound to one is unsupported_app; other charts are unaffected."""
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, "Use a dark blue accent for this component")
    use_model(monkeypatch, app, {"source_id": sid, "text": "Use a dark blue accent for this component",
        "needs": [{"capability": "style.colors", "value": ["#172554"]}], "component_ids": [component_id]})
    _, a = check(client, app, bid)
    statuses = [(i["status"], i["reason"]) for i in a["issues"]]
    if status:
        assert a["state"] == "blocked" and any(s == status and "Scorecards" in r and "colors" in r for s, r in statuses), a
    else:
        assert not any(s == "unsupported_app" for s, _ in statuses), a


def recreate_blueprint(snapshot, rows=None):
    """A recreate snapshot with a staged Blueprint answering the 18.2 fixture (task 22.1)."""
    from test_blueprint import fixture
    context = fixture('context')
    context.update(datasets=[{'source_id': 's', 'summary': 'Sales'}], derived_fields=[])
    ids = dict(zip(('revenue', 'orders', 'units'), [k['id'] for k in context['kpis']]))
    rows = RECREATE['rows'] if rows is None else rows
    outline = fixture('outline')
    template = outline['sections'][0]['questions'][0]
    outline['sections'] = [{'id': 's1', 'title': 'Store', 'purpose': 'Recreate.', 'questions': [
        {**template, 'id': qid, 'text': text, 'kpi_refs': [ids[k] for k in dict.fromkeys(r['kpi'] for r in rows if r['question_id'] == qid)]}
        for qid, text in RECREATE['questions'].items()]}]
    blueprint = fixture('blueprint')
    blueprint.update(view_sources={'base': 's', 'joins': [], 'union': []}, derived_fields=[RECREATE['derived_field']],
                     rows=[{'question_id': r['question_id'], 'section_id': 's1', 'page': 1, 'note': '', 'status': 'ok',
                            'issue_ids': [], 'component': r['component']} for r in rows])
    snapshot = {**snapshot, 'context': context, 'outline': outline, 'design': fixture('design'), 'blueprint': blueprint,
                'confirmed_kpis': context['kpis'], 'blueprint_errors': []}
    snapshot['sources'][0]['bq_table'] = snapshot['sources'][0]['table']
    return snapshot


def observation_verdicts(snapshot, ledger):
    from dss.artifacts.models import Blueprint
    from dss.spec import feasibility
    bp = Blueprint.model_validate(snapshot['blueprint'])
    checker = capabilities.Checker(capabilities.load_registry())
    return {r.source.item_id or r.text: indices for r, _, _, indices, _ in feasibility.coverage(snapshot, ledger, checker, bp.rows, bp.derived_fields)}


def test_blueprint_observation_coverage_binds_rows_and_shares_one_row():
    """22.1: every observation names the rows that fulfil it; two observations one row satisfies are both bound to it."""
    items = [*RECREATE['items'], {**RECREATE['items'][4]}]
    extraction = {**RECREATE['extraction'], 'o7': RECREATE['extraction']['o5']}
    snapshot = recreate_blueprint(recreate_snapshot(items=items))
    ledger, a = recreate_assess(snapshot, extraction)
    assert a.state == 'ready', [i.reason for i in a.issues]
    assert observation_verdicts(snapshot, ledger) == {'o2': [0], 'o3': [1], 'o4': [2], 'o5': [3], 'o6': [4], 'o7': [3]}


def test_blueprint_observation_keeps_its_own_verdict():
    """An unsupported observation keeps its existing verdict; no Blueprint issue doubles it."""
    extraction = copy.deepcopy(RECREATE['extraction'])
    extraction['o3']['needs'].append({'capability': 'animation.temporal_playback'})
    snapshot = recreate_blueprint(recreate_snapshot())
    ledger, a = recreate_assess(snapshot, extraction)
    target = next(r for r in ledger.requirements if r.source.item_id == 'o3')
    assert [i.status for i in a.issues if i.requirement == target.text] == ['unsupported_app']
    assert not any(i.requirement.startswith('Observation') for i in a.issues)
    assert 'o3' not in observation_verdicts(snapshot, ledger)


def test_blueprint_observation_gap_is_an_issue_with_a_bucket_alternative():
    rows = copy.deepcopy(RECREATE['rows'])
    rows[3]['component'].update(date_dimension='order_date')
    snapshot = recreate_blueprint(recreate_snapshot(), rows)
    ledger, a = recreate_assess(snapshot)
    [issue] = [i for i in a.issues if i.requirement.startswith('Observation')]
    assert a.state == 'blocked' and issue.status == 'needs_clarification' and 'no month bucket of order_date' in issue.reason
    assert [alt.id for alt in issue.alternatives] == ['date_bucket']
    assert observation_verdicts(snapshot, ledger)['o5'] == []


def test_style_and_data_builds_skip_observation_coverage(monkeypatch):
    """No recreate reference: no observation pass at all (unchanged behavior and bytes)."""
    from dss.spec import feasibility
    monkeypatch.setattr(req, '_requirement_issues', lambda *a: pytest.fail('no observation pass'))
    checker = capabilities.Checker(capabilities.load_registry())
    data = staged_snapshot(1, 1)
    style = {**data, 'reference': {'id': 'ref', 'mode': 'style', 'instructions': '', 'images': [], 'interpretation': {'items': []}}}
    for snapshot in (data, style):
        assert req.blueprint_observations(snapshot, req.Ledger(), checker) == []
        assert not any(e['code'] == 'observation' for e in feasibility.diagnostics(snapshot, req.Ledger(), checker))


def test_recreate_blueprint_recompute_speed_with_24_observations(record_property):
    """The deterministic recomputation, observation coverage on Blueprint rows included, stays within 250 ms warm."""
    items = [{**RECREATE['items'][1 + n % 5], 'label': f'Chart {n}'} for n in range(24)]
    extraction = {f'o{n + 1}': RECREATE['extraction'][f'o{2 + n % 5}'] for n in range(24)}
    extraction['instructions'] = RECREATE['extraction']['instructions']
    checker = capabilities.Checker(capabilities.load_registry())
    # Every observation fulfilled, then every one a gap with alternatives to validate (no bucket, no table).
    gaps = copy.deepcopy(RECREATE['rows'])
    gaps[3]['component']['date_dimension'] = 'order_date'
    gaps[4]['component']['type'] = 'table'
    for rows, state in ((None, 'ready'), (gaps, 'blocked')):
        snapshot = recreate_blueprint(recreate_snapshot((NET,), RECREATE['instructions'], items=items), rows)
        ledger, a = recreate_assess(snapshot, extraction)
        assert a.state == state, [i.reason for i in a.issues]
        verdicts = observation_verdicts(snapshot, ledger)
        assert len([k for k in verdicts if k.startswith('o')]) == 24
        assert all(verdicts.values()) if rows is None else len([i for i in a.issues if i.requirement.startswith('Observation')]) >= 9
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            req.evaluate(snapshot, ledger, checker, check_components=False)
            timings.append(time.perf_counter() - start)
        record_property(f'recompute_{state}_first_sample_s', timings[0])
        record_property(f'recompute_{state}_samples_s', json.dumps(timings))
        assert min(timings) < .250, (state, timings)


# 24.11: evaluation-local reuse must not become authorization across calls.
RECOMPUTE_CHANGES = ('instructions', 'kpi_meaning', 'kpi_unit', 'source_identity', 'reference_identity',
                     'image_identity', 'page', 'title', 'mappings', 'decisions', 'allowed_types')


def recompute_mutation(snapshot, ledger, checker, change):
    """Mutate the same objects a previous evaluate read, as an edit/recheck does."""
    if change == 'instructions':
        text = snapshot['reference']['instructions'].replace('SUM(revenue)', 'AVG(revenue)')
        snapshot['reference']['instructions'] = text
        snapshot['incoming'][0]['text'] = text
    elif change == 'kpi_meaning':
        snapshot['confirmed_kpis'][0]['measure']['agg'] = 'avg'
    elif change == 'kpi_unit':
        snapshot['confirmed_kpis'][0]['unit'] = 'EUR'
    elif change == 'source_identity':
        snapshot['sources'][0].update(table='p.d.replacement', bq_table='p.d.replacement')
    elif change == 'reference_identity':
        snapshot['reference']['id'] = 'ref_replaced'
    elif change == 'image_identity':
        snapshot['reference']['images'][0]['id'] = 'img_replaced'
        snapshot['incoming'][1]['image_id'] = 'img_replaced'
    elif change == 'page':
        for row in snapshot['blueprint']['rows']:
            row['page'] = 2
    elif change == 'title':
        ledger.requirements[0].properties = [req.Property(path='label', value='Revenue in 2011')]
    elif change == 'mappings':
        ledger.requirements[0].mappings[0].aggregation = 'avg'
    elif change == 'decisions':
        ledger.decisions.append(req.observation_drop(snapshot, ledger, ledger.requirements[0].id, 'bp_test_drop'))
    elif change == 'allowed_types':
        checker = capabilities.Checker(checker.registry, allowed=checker.allowed - {'scorecard'})
    else:
        raise AssertionError(change)
    return checker


def assessment_value(assessment):
    return assessment.model_dump(mode='json', exclude={'id'})


@pytest.mark.parametrize('blocked', [False, True])
def test_recompute_repeated_call_purity(blocked):
    rows = copy.deepcopy(RECREATE['rows'])
    if blocked:
        rows[3]['component']['date_dimension'] = 'order_date'
        rows[4]['component']['type'] = 'table'
    snapshot = recreate_blueprint(recreate_snapshot((NET,), RECREATE['instructions']), rows)
    ledger, baseline = recreate_assess(snapshot)
    checker = capabilities.Checker(capabilities.load_registry())
    original = copy.deepcopy((snapshot, ledger.model_dump(mode='json')))
    values = [req.evaluate(snapshot, ledger, checker, check_components=False) for _ in range(3)]
    assert baseline.state == ('blocked' if blocked else 'ready')
    assert all(assessment_value(a) == assessment_value(baseline) for a in values)
    assert len({a.id for a in [baseline, *values]}) == 4
    assert (snapshot, ledger.model_dump(mode='json')) == original


@pytest.mark.parametrize('change', RECOMPUTE_CHANGES)
def test_recompute_cross_call_invalidation(change):
    snapshot = recreate_blueprint(recreate_snapshot((copy.deepcopy(NET),), RECREATE['instructions']))
    ledger, _ = recreate_assess(snapshot)
    checker = capabilities.Checker(capabilities.load_registry())
    original_snapshot, original_ledger = copy.deepcopy(snapshot), ledger.model_copy(deep=True)
    before = req.evaluate(snapshot, ledger, checker, check_components=False)
    assert before.state == 'ready'
    ledger.assessment = before
    changed_checker = recompute_mutation(snapshot, ledger, checker, change)
    edited = copy.deepcopy((snapshot, ledger.model_dump(mode='json')))
    stale = req.get(snapshot, ledger, changed_checker)
    assert stale.state == 'stale' and stale.id is None
    after = req.evaluate(snapshot, ledger, changed_checker, check_components=False)
    assert after.input_digest != before.input_digest
    if change in ('instructions', 'kpi_meaning', 'kpi_unit', 'image_identity',
                  'page', 'mappings', 'allowed_types'):
        assert after.state == 'blocked', (change, after)
    if change in ('instructions', 'kpi_meaning', 'kpi_unit', 'mappings'):
        assert any(i.id.startswith('obs_stale_') for i in after.issues)
    if change == 'page':
        assert not any(observation_verdicts(snapshot, ledger).values())
    if change == 'reference_identity':
        assert req.blueprint_observations(snapshot, ledger, changed_checker) == []
    if change == 'title':
        r = ledger.requirements[0]
        assert req.observation_meaning(r, r.needs, r.properties, kpis=snapshot['confirmed_kpis'])['title'] == 'Revenue (USD)'
    if change == 'decisions':
        assert ledger.requirements[0].id not in {r.id for r, *_ in req.blueprint_observations(snapshot, ledger, changed_checker)}
    again = req.evaluate(snapshot, ledger, changed_checker, check_components=False)
    assert assessment_value(again) == assessment_value(after)
    assert (snapshot, ledger.model_dump(mode='json')) == edited
    # Restoring the earlier evidence restores its whole assessment, not only readiness.
    snapshot.clear()
    snapshot.update(original_snapshot)
    ledger = original_ledger
    assert assessment_value(req.evaluate(snapshot, ledger, checker, check_components=False)) == assessment_value(before)


# 24.10: the screenshot title as code assigns it (architecture.md#Recreate page placement and truthful observed titles).
REVENUE, ORDERS = RECREATE['items'][1], RECREATE['items'][2]
UNITS_SOLD = {'id': 'units_sold', 'name': 'Units sold', 'unit': 'units', 'measure': {'field': 'quantity', 'agg': 'sum'}, 'ratio': None}


def observed(item, extraction, kpis=(NET,), instructions=''):
    """One recreate observation (o2) reconciled under these definitions, with the confirmed KPIs."""
    snapshot = recreate_snapshot(kpis, instructions, items=[RECREATE['items'][0], item])
    ledger, _ = recreate_assess(snapshot, {'o2': extraction, 'instructions': RECREATE['extraction']['instructions']})
    r = next(r for r in ledger.requirements if r.source.item_id == 'o2')
    assert not r.mapping_conflicts, r.mapping_conflicts
    return r, snapshot['confirmed_kpis']


@pytest.mark.parametrize('label, title', [
    ('Orders in 2011', 'Orders'), ('Orders for 2000-2019', 'Orders'), ('Orders 2000–2019', 'Orders'),
    ('Orders 2000-19', 'Orders'), ('Orders Q3 2024', 'Orders'), ('Orders in Q3 2024', 'Orders'), ('Orders 2024 Q3', 'Orders'),
    ('Orders as of March 2024', 'Orders'), ('Orders March 2024', 'Orders'), ('Orders, Sept. 2024', 'Orders'),
    ('Orders since 2015', 'Orders'), ('Orders during 2020', 'Orders'), ('Orders (2000-2019)', 'Orders'),
    ('Orders - for 2011', 'Orders'), ('ORDERS IN 2011', 'ORDERS'),
    # Kept: a bare year (a name), a period mid-label, a label that is only a period phrase.
    ('Vision 2030', 'Vision 2030'), ('Orders 2024', 'Orders 2024'), ('Orders in 2011 by region', 'Orders in 2011 by region'),
    ('in 2011', 'in 2011'), ('Q3 2024', 'Q3 2024'), ('March 2024', 'March 2024'), ('Orders in 1000', 'Orders in 1000'),
    # A comparison keeps its end period: stripping it would leave the title dangling.
    ('Orders Q1 2024 vs Q1 2023', 'Orders Q1 2024 vs Q1 2023'), ('Orders 2023 versus March 2024', 'Orders 2023 versus March 2024'),
])
def test_observed_title_drops_only_a_trailing_unenforced_period(label, title):
    r, kpis = observed({**ORDERS, 'label': label}, RECREATE['extraction']['o3'], kpis=(), instructions='Orders = COUNT(DISTINCT order_id)')
    assert req.observed_title(label, r, kpis) == title


@pytest.mark.parametrize('case, kpis, instructions, title', [
    ('confirmed KPI unit', (NET,), '', 'Revenue (USD)'),
    ('instruction unit', RECREATE['unmatched_kpis'], RECREATE['instructions'], 'Revenue (USD)'),
    ('surface definition unit', (), 'Revenue = SUM(revenue), unit USD', 'Revenue (USD)'),
    ('surface definition, KPI unit', (NET,), 'Revenue = SUM(revenue), chart scorecard', 'Revenue (USD)'),
    # The extractor read "USD" in the image; no definition or KPI states it.
    ('extractor-only unit', (), 'Revenue = SUM(revenue), chart scorecard', 'Revenue'),
])
def test_observed_title_unit_comes_only_from_definitions_and_kpis(case, kpis, instructions, title):
    r, confirmed = observed(REVENUE, RECREATE['extraction']['o2'], kpis, instructions)
    assert r.mappings[0].unit == 'USD', case
    assert req.observed_title('Revenue in 2011', r, confirmed) == title, case
    assert req.observed_title('Revenue', r, confirmed) == title, case
    # Idempotent: a code-assigned title is its own normalization.
    assert req.observed_title(title, r, confirmed) == title
    if case == 'surface definition, KPI unit':
        assert req.observed_title('Revenue', r, None) == 'Revenue'  # a KPI-only unit needs the confirmed KPIs


@pytest.mark.parametrize('label', ['Revenue (USD)', 'Revenue in $', 'Revenue, US dollars', 'Revenue usd'])
def test_observed_title_never_repeats_a_shown_unit(label):
    r, kpis = observed(REVENUE, RECREATE['extraction']['o2'])
    assert req.observed_title(label, r, kpis) == label
    item = {**ORDERS, 'unit': '%'}
    r, kpis = observed(item, RECREATE['extraction']['o3'], kpis=(), instructions='Orders = COUNT(DISTINCT order_id), unit %')
    for shown in ('Share of orders (percent)', 'Orders %', 'Orders, pct'):
        assert req.observed_title(shown, r, kpis) == shown
    assert req.observed_title('Orders in 2011', r, kpis) == 'Orders (%)'


def test_observed_title_mixed_units_and_label_rule_add_nothing():
    two = {**RECREATE['extraction']['o2'], 'mappings': [*RECREATE['extraction']['o2']['mappings'],
                                                       {'label': 'Units sold', 'field': 'quantity', 'aggregation': 'sum'}]}
    r, kpis = observed(REVENUE, two, kpis=(NET, UNITS_SOLD))
    assert [m.unit for m in r.mappings] == ['USD', 'units']
    assert req.observed_title('Revenue in 2011', r, kpis) == 'Revenue'
    # A suffix the label rule rejects is dropped for this title only.
    quoted = {**NET, 'unit': '", "'}
    item, extraction = {**REVENUE, 'unit': None}, copy.deepcopy(RECREATE['extraction']['o2'])
    extraction['mappings'][0]['unit'] = None
    r, kpis = observed(item, extraction, kpis=(quoted,))
    assert r.mappings[0].unit == '", "' and req.observed_title('Revenue in 2011', r, kpis) == 'Revenue'


def test_observed_titles_feed_planner_meaning_simulated_titling_and_label_check_alike():
    """One normalizer: the planner meaning, the simulated Blueprint titling and the label check agree; a planner
    title equal to the raw screenshot title is normalized at titling; a suffix failing the label rule on one
    observation never makes another observation's title fall back."""
    items = [RECREATE['items'][0], {**REVENUE, 'label': 'Revenue in 2011'}, *RECREATE['items'][2:]]
    rows = copy.deepcopy(RECREATE['rows'])
    rows[0]['component']['label'] = 'Revenue in 2011'  # the planner copied the raw screenshot title
    snapshot = recreate_blueprint(recreate_snapshot(items=items), rows)
    # Units sold's confirmed unit fails the label rule as a suffix: only that title goes without it.
    snapshot['confirmed_kpis'] = [{**k, 'unit': '", "'} if k['id'] == 'units_sold' else k for k in snapshot['confirmed_kpis']]
    # The extractor reads each chart's title as its label property.
    extraction = {f'o{n}': {**RECREATE['extraction'][f'o{n}'], 'properties': [{'path': 'label', 'value': items[n - 1]['label']}]}
                  for n in range(2, 7)}
    ledger, a = recreate_assess(snapshot, {**extraction, 'instructions': RECREATE['extraction']['instructions']})
    assert a.state == 'ready', [i.reason for i in a.issues]
    checker = capabilities.Checker(capabilities.load_registry())
    found = {r.source.item_id: (r, needs, props) for r, needs, props in req.blueprint_observations(snapshot, ledger, checker)}
    titles = {oid: req.observation_meaning(*o, kpis=snapshot['confirmed_kpis']).get('title') for oid, o in found.items()}
    assert titles == {'o2': 'Revenue (USD)', 'o3': 'Orders', 'o4': 'Units sold', 'o5': 'Revenue by month (USD)',
                      'o6': 'Revenue by region (USD)'}
    # Each row takes its observation's code-assigned title: none falls back.
    assert observation_verdicts(snapshot, ledger) == {'o2': [0], 'o3': [1], 'o4': [2], 'o5': [3], 'o6': [4]}
    # The label check: the code-assigned title fulfils; the raw screenshot title no longer does.
    r, needs, props = found['o2']
    active = r.model_copy(update={'properties': req._observed_properties(r, props, snapshot)})
    component = {**rows[0]['component'], 'id': 'p1_revenue'}
    assert req._component_fulfills({**component, 'label': 'Revenue (USD)'}, active, needs, checker, snapshot)
    assert not req._component_fulfills(component, active, needs, checker, snapshot)


# 24.3: comment checks fit a long build.
LEDGER_HEADER = "Current ledger and explicit decisions (untrusted data):\n"
SOURCES_HEADER = "New sources (untrusted; preserve IDs):\n"


def section_json(text, header):
    return json.JSONDecoder().raw_decode(text.split(header, 1)[1])[0]


def old_row(i, component_ids=()):
    """A durable row with provenance (comment source, clarification, KPI origin). A row bound to a
    removed component (p1_gone) has a message source: a full-ledger merge would unbind it."""
    gone = list(component_ids) == ["p1_gone"]
    source = req.Source(id=f"m_old_{i}:0", kind="message" if gone else "comment", text=f"Old request {i}",
                        component_id=component_ids[0] if component_ids and not gone else None)
    return req.Requirement(id=f"req_old_{i:02d}", source=source, text=f"Old request {i}",
        needs=[capabilities.Need(capability="chart.bar")], component_ids=list(component_ids),
        clarifications=[req.Source(id=f"m_def_{i}", kind="message", text=f"Definition {i}")],
        mapping_origins={"kpi:revenue": f"net_revenue_{i}:revenue:sum:"})


def long_ledger():
    """30 rows: 3 bound to the comment's target, 7 unbound, 20 bound to other components."""
    others = ["p1_revenue", "p1_note", "p1_gone"]
    return req.Ledger(requirements=[old_row(i, ["p1_regions"]) for i in range(3)] + [old_row(i) for i in range(3, 10)]
                      + [old_row(i, [others[i % 3]]) for i in range(10, 30)])


class BatchModel(Capture):
    """Answers each new source it was sent with one unsupported row (the check then blocks)."""

    async def generate_content_async(self, llm_request, stream=False):
        sources = section_json(str(llm_request.config.system_instruction), SOURCES_HEADER)
        self.response = json.dumps({"requirements": [extracted(s["id"], "animation.temporal_playback", s["text"])
                                                     for s in sources]})
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def test_comment_batch_sends_target_and_unbound_rows_and_keeps_the_rest(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    original = long_ledger()
    req.save(folder, original)
    model = BatchModel(response="", requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    accepted = client.post(f"/api/builds/{bid}/comments",
                           json={"comments": [{"component_id": "p1_regions", "text": "Animate these bars"}]})
    assert accepted.status_code == 202, accepted.text
    client.portal.call(drain, app)
    [request] = model.requests
    sent = section_json(str(request.config.system_instruction), LEDGER_HEADER)["requirements"]
    assert [r["id"] for r in sent] == [r.id for r in original.requirements[:10]]
    ledger = req.load(folder)
    assert [r.id for r in ledger.requirements[:30]] == [r.id for r in original.requirements]
    # Every unsent row is unchanged, provenance included (a full-ledger merge unbinds p1_gone's rows).
    for before, after in zip(original.requirements[10:], ledger.requirements[10:30]):
        assert after.model_dump() == before.model_dump()
    [new] = ledger.requirements[30:]
    assert new.component_ids == ["p1_regions"] and new.source.batch_id == ledger.pending_comments.id
    assert ledger.assessment.state == "blocked" and not ledger.scope_error
    with app.state.db.connect() as conn:
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE run_id=?", (accepted.json()["run_id"],)).fetchone()[0])
    [span] = [s for s in spans if s["node"] == "capability_check"]
    assert span["ledger_rows_sent"] == 10 and span["ledger_rows_kept"] == 20


def test_only_a_comment_batch_trims_the_ledger():
    ledger = long_ledger()
    comment = {"id": "b:0", "kind": "comment", "text": "Bigger", "component_id": "p1_regions"}
    message = {"id": "m", "kind": "message", "text": "Add a map"}
    image = {"id": "ref:o1", "kind": "image", "text": "{}", "reference_id": "ref", "item_id": "o1"}
    assert [r.id for r in req.sent_requirements(ledger, [comment])] == [r.id for r in ledger.requirements[:10]]
    for incoming in ([message], [image], [comment, message], []):
        assert req.sent_requirements(ledger, incoming) == ledger.requirements


def test_keep_unsent_restores_rows_a_merge_touched():
    before = long_ledger()
    after = before.model_copy(deep=True)
    after.requirements[12].clarifications, after.requirements[12].component_ids = [], []
    after.requirements[0].superseded = {"need:0": "req_new"}
    del after.requirements[20]
    after.requirements.append(old_row(40, ["p1_regions"]))
    kept = req.keep_unsent(before, after, before.requirements[:10])
    assert [r.id for r in kept.requirements] == [r.id for r in before.requirements] + ["req_old_40"]
    assert kept.requirements[12] == before.requirements[12] and kept.requirements[20] == before.requirements[20]
    assert kept.requirements[0].superseded == {"need:0": "req_new"}  # sent rows keep the merge's changes
    with pytest.raises(ValueError, match="Requirement scope exceeded"):
        req.keep_unsent(before, after.model_copy(update={"requirements": after.requirements + [
            old_row(50 + i) for i in range(10)]}), before.requirements[:10])


@pytest.mark.parametrize("decided,scope", [(6, False), (4, True)])
def test_issue_cap_counts_only_active_issues(thin, decided, scope):
    client, app, bid, folder = thin
    rows = [req.Requirement(id=f"req_u{i:02d}", source=req.Source(id="m_many", kind="message", text="Many unknowns"),
                            text=f"Unknown {i}", needs=[capabilities.Need(capability="unknown.feature")]) for i in range(25)]
    ledger = req.Ledger(requirements=rows, decisions=[{"requirement_id": r.id, "meaning": req.meaning(r), "action": "drop"}
                                                      for r in rows[:decided]])
    snapshot, checker = req.inputs(app.state.db, bid, folder), capabilities.Checker(capabilities.load_registry())
    a = req.evaluate(snapshot, ledger, checker)
    if scope:
        [issue] = a.issues
        assert issue.reason == "21 active issues, over the 20-issue limit; drop or clarify some requests, then check again"
    else:
        assert len(a.issues) == 25 and sum(i.resolution == "dropped" for i in a.issues) == 6
        assert not any(i.id == "issue_scope" for i in a.issues)
    req.save(folder, ledger, a)
    assert len(req.load(folder).assessment.issues) == len(a.issues)


# 24.7: recreate observation completion (architecture.md#Recreate observation completion).
ELECTRICITY = json.loads((Path(__file__).parent / 'data/recreate_electricity.json').read_text(encoding='utf-8'))
POWER = {c['name']: c['bq_type'] for c in ELECTRICITY['columns']}
CLAUSES = [c['text'] for c in ELECTRICITY['extraction']['instructions']]


def power_snapshot(instructions=None, items=None, rid='ref_power'):
    """What inputs() returns for the 24.7 electricity reference, its confirmed KPIs and profiled columns."""
    text = ELECTRICITY['instructions'] if instructions is None else instructions
    snapshot = recreate_snapshot(ELECTRICITY['kpis'], text, POWER, ELECTRICITY['items'] if items is None else items, rid)
    snapshot['sources'][0]['columns'] = [{k: c[k] for k in ('name', 'type', 'bq_type', 'date_like')} for c in ELECTRICITY['columns']]
    return snapshot


def power_extraction(instructions=None, **items):
    """The fixture's extraction; `instructions` replaces the instruction records (one per clause)."""
    extraction = copy.deepcopy(ELECTRICITY['extraction'])
    if instructions is not None:
        extraction['instructions'] = [{'text': c, 'needs': [], 'mappings': []} for c in instructions]
    extraction.update(items)
    return extraction


def assess(snapshot, extraction, ledger=None):
    """recreate_assess with one extraction record per clause of the instructions."""
    rid = snapshot['reference']['id']
    known = {s['id'] for s in req.new_sources(snapshot, ledger or req.Ledger())}  # what the extractor is sent
    items = [{'source_id': f'{rid}:{oid}', **e} for oid, records in extraction.items() if f'{rid}:{oid}' in known
             for e in (records if isinstance(records, list) else [records])]
    checker = capabilities.Checker(capabilities.load_registry())
    ledger = req.merge(ledger or req.Ledger(), snapshot, req.Extraction.model_validate({'requirements': items}))
    return ledger, req.evaluate(snapshot, ledger, checker, check_components=False)


def power_assess(clauses=None, snapshot=None, ledger=None):
    """A check of the fixture (or of `clauses`); with `ledger`, a recheck of already extracted sources."""
    snapshot = snapshot or power_snapshot(' '.join(clauses) if clauses is not None else None)
    return (*assess(snapshot, {} if ledger else power_extraction(clauses), ledger), snapshot)


@pytest.fixture
def catalog_types(monkeypatch):
    """The recipe 1.3 catalog (area, fixed_size_list), whatever the root .env narrows DSS_ALLOWED_TYPES to."""
    from dss.spec.models import TYPES
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))


def by_item(ledger):
    return {r.source.item_id: r for r in ledger.requirements if r.source.kind == 'image'}


def unresolved(a, row):
    return [(i.status, i.reason) for i in a.issues if i.requirement == row.text and i.resolution == 'unresolved']


def power_blueprint(snapshot, rows=None):
    """The 24.7 fixture's staged Blueprint (its release rows, three per-section pages)."""
    from test_blueprint import fixture
    context = fixture('context')
    context.update(datasets=[{'source_id': 's', 'summary': 'Electricity'}], derived_fields=[], kpis=ELECTRICITY['kpis'])
    blueprint = fixture('blueprint')
    blueprint.update(view_sources={'base': 's', 'joins': [], 'union': []}, derived_fields=[],
                     rows=copy.deepcopy(ELECTRICITY['rows'] if rows is None else rows))
    snapshot = {**snapshot, 'context': context, 'outline': {'revision': 1, 'sections': ELECTRICITY['sections']},
                'design': fixture('design'), 'blueprint': blueprint, 'blueprint_errors': []}
    snapshot['sources'][0]['bq_table'] = snapshot['sources'][0]['table']
    return snapshot


def dropped(ledger, a, snapshot):
    """The user's approved drops of the remaining observation issues."""
    ledger.decisions = [req.observation_drop(snapshot, ledger, next(r.id for r in ledger.requirements if r.text == i.requirement), i.id)
                        for i in a.issues if i.resolution == 'unresolved']
    return ledger


def completed(snapshot, ledger):
    from dss.artifacts.models import Blueprint, Context
    from dss.spec import feasibility
    checker = capabilities.Checker(capabilities.load_registry())
    return feasibility.complete(snapshot, ledger, checker, Blueprint.model_validate(snapshot['blueprint']),
                                snapshot['sources'], Context.model_validate(snapshot['context']))


@pytest.mark.usefixtures('catalog_types')
def test_definition_clauses_are_evidence_not_requirement_rows():
    """24.7 block: each definition-only instruction clause was an `unknown` requirement row (12 in run 104805)."""
    ledger, a, snapshot = power_assess()
    # Code reads definition-only instructions itself: the extractor is never sent them (live: 30 s deadline).
    assert 'ref_power:instructions' not in {s['id'] for s in req.new_sources(snapshot, req.Ledger())}
    assert not [r for r in ledger.requirements if r.source.kind == 'reference']
    assert not any(i.status == 'unknown' for i in a.issues), a.issues
    rows = by_item(ledger)
    assert sorted(rows, key=lambda o: int(o[1:])) == ['o2', 'o3', 'o5', 'o6', 'o7', 'o8', 'o9', 'o10', 'o11']  # none dropped
    # Only the approved drop classes remain: the geo map lacks a GEO field, the legend control has no field.
    assert {o: unresolved(a, r) for o, r in rows.items() if unresolved(a, r)} == {
        'o5': [('needs_data', 'Geo chart needs a geo_field field (GEO/GEOGRAPHY) that the connected data lacks')],
        'o7': [('needs_clarification', 'Choose which field supplies control_field for Drop-down list control')]}
    assert req.unused_definitions(snapshot, ledger) == ['Region', 'Country', 'Urban', 'Rural']
    # A fixed point: recomputation on unchanged inputs changes nothing.
    assert req.merge(ledger, snapshot, req.Extraction(requirements=[])).requirements == ledger.requirements


@pytest.mark.usefixtures('catalog_types')
def test_a_mixed_sentence_stays_a_requirement_and_bad_definitions_block():
    mixed = 'Region Selector = region and make it blue.'
    ledger, a, _ = power_assess([*CLAUSES[1:], mixed])
    [row] = [r for r in ledger.requirements if r.source.kind == 'reference']
    assert row.text == mixed and unresolved(a, row) == [('unknown', 'No registered capability covers this requirement; clarify the requested behavior')]
    missing = [c.replace('SUM(people_without_access)', 'SUM(households_without_power)') for c in CLAUSES]
    ledger, a, _ = power_assess(missing)
    assert unresolved(a, by_item(ledger)['o6']) == [('needs_data', 'Field households_without_power is not in the connected data')]
    conflicting = [*CLAUSES, 'People without access to electricity = AVG(people_without_access), date grain year using year.']
    ledger, a, _ = power_assess(conflicting)
    assert [s for s, r in unresolved(a, by_item(ledger)['o6']) if 'Conflicting definitions for People without access' in r] == ['needs_clarification']
    assert not [r for r in ledger.requirements if r.source.kind == 'reference']
    # An unknown aggregation is not a definition: its clause stays an unknown row.
    median = [*CLAUSES, 'Median access = MEDIAN(access_pct).']
    ledger, a, _ = power_assess(median)
    [row] = [r for r in ledger.requirements if r.source.kind == 'reference']
    assert row.text == 'Median access = MEDIAN(access_pct).' and unresolved(a, row)[0][0] == 'unknown'


@pytest.mark.usefixtures('catalog_types')
def test_field_definition_binds_the_control_field_and_its_chart_type():
    ledger, a, _ = power_assess()
    selector = by_item(ledger)['o2']
    assert selector.needs == [capabilities.Need(capability='control.fixed_size_list', fields={'control_field': 'region'})]
    assert selector.mappings == [req.Mapping(label='Region Selector', field='region')] and not unresolved(a, selector)
    assert json.loads(selector.mapping_origins['observed:0'])['evidence'] == ['ref_power:instructions']
    for chart, reason in (('sparkline', 'Chart sparkline is not a catalog type'), ('scorecard', 'Chart scorecard cannot show Region Selector')):
        clauses = [CLAUSES[0].replace('fixed_size_list', chart), *CLAUSES[1:]]
        ledger, a, _ = power_assess(clauses)
        found = unresolved(a, by_item(ledger)['o2'])
        assert [s for s, r in found if r.startswith(reason)] == ['needs_clarification'], found
    # Without the clause the extractor's proposed field is no definition.
    ledger, a, _ = power_assess(CLAUSES[1:])
    assert any('Confirm which field defines Region Selector' in r for _, r in unresolved(a, by_item(ledger)['o2']))


@pytest.mark.usefixtures('catalog_types')
def test_using_binds_the_date_field_and_must_name_a_date():
    ledger, a, _ = power_assess()
    rows = by_item(ledger)
    assert rows['o6'].mapping_origins['using'] == 'year' and not unresolved(a, rows['o6'])
    assert [n.model_dump(exclude_defaults=True) for n in rows['o8'].needs] == [
        {'capability': 'chart.area', 'fields': {'date_field': 'year'}},
        {'capability': 'option.area.date_granularity', 'value': 'year', 'fields': {'date_field': 'year'}},
        {'capability': 'argument.title'}]
    assert rows['o8'].mappings == [req.Mapping(label='Philippines', field=f, unit='%', aggregation='avg', date_grain='year')
                                   for f in ('urban_pct', 'rural_pct')]
    clauses = [c.replace('using year', 'using country') if c.startswith('People without') else c for c in CLAUSES]
    ledger, a, _ = power_assess(clauses)
    assert ('needs_clarification', 'Date grain year for People without access to electricity uses country; '
            'name a DATE, DATETIME or TIMESTAMP field') in unresolved(a, by_item(ledger)['o6'])
    assert 'observed:0' not in by_item(ledger)['o6'].mapping_origins  # nothing was authorized
    # Removing the instructions restores each observation's own extraction.
    restored, _, _ = power_assess([], snapshot=power_snapshot(''), ledger=ledger)
    assert by_item(restored)['o8'].needs == [capabilities.Need.model_validate(n) for n in ELECTRICITY['extraction']['o8']['needs']]
    assert not any(k in r.mapping_origins for r in by_item(restored).values() for k in ('surface', 'using', 'observed:1'))


@pytest.mark.usefixtures('catalog_types')
def test_scorecard_observation_skips_the_date_grain_and_the_bar_is_code_added():
    from dss.artifacts.models import BlueprintRow
    from dss.spec import feasibility
    ledger, a, snapshot = power_assess()
    ledger = dropped(ledger, a, snapshot)
    snapshot = power_blueprint(snapshot)
    checker = capabilities.Checker(capabilities.load_registry())
    verdicts = observation_verdicts(snapshot, ledger)
    scorecard = next(i for i, r in enumerate(ELECTRICITY['rows']) if r['question_id'] == 'q1')
    # 24.10: the planner's region list is on page 2; the reference's counts only on page 1.
    assert verdicts['o3'] == [scorecard] and verdicts['o2'] == [] and verdicts['o6'] == [] and verdicts['o8'] == []
    rows, derived, added = completed(snapshot, ledger)
    assert [(r.question_id, r.page, r.note, r.component.type) for r in added] == [
        (None, 1, 'observation ref_power:o6', 'bar'), (None, 1, 'observation ref_power:o8', 'area')]
    bar, area = (r.component for r in added)
    assert (bar.label, bar.dimensions, bar.date_dimension, [m.model_dump() for m in bar.metrics]) == (
        'People without access to electricity', ['year_year'], None, [{'field': 'people_without_access', 'agg': 'sum'}])
    assert (area.date_dimension, area.dimensions, area.options, [m.field for m in area.metrics]) == (
        'year_year', [], {'date_granularity': 'year'}, ['urban_pct', 'rural_pct'])
    assert [f.model_dump() for f in derived] == [{'name': 'year_year', 'expression': 'DATE_TRUNC(year, YEAR)', 'type': 'date',
                                                  'description': 'Year of year'}]
    done = {**snapshot, 'blueprint': {**snapshot['blueprint'], 'rows': [r.model_dump() for r in rows],
                                      'derived_fields': [f.model_dump() for f in derived]}}
    # Its Issue offers the observed type on the nearest page-1 row, the Region dropdown; completion leaves that
    # choice to the user. Accepting it binds the region list on page 1.
    dropdown = next(i for i, r in enumerate(rows) if r.page == 1 and r.component.type == 'dropdown')
    [region] = [e for e in feasibility.diagnostics(done, ledger, checker) if e['code'] == 'observation']
    assert region['indices'] == [dropdown] and [o['id'] for o in region['offers']] == ['observed_type']
    rows[dropdown] = BlueprintRow.model_validate(region['offers'][0]['replace'][0]['row'])
    done['blueprint']['rows'] = [r.model_dump() for r in rows]
    verdicts = observation_verdicts(done, ledger)
    # Every other observation is bound to a real row; the four per-country ones share the one area row.
    assert verdicts['o2'] == [dropdown] and rows[dropdown].component.type == 'fixed_size_list'
    assert verdicts['o6'] == [len(rows) - 2] and all(verdicts[o] == [len(rows) - 1] for o in ('o8', 'o9', 'o10', 'o11'))
    assert req.evaluate(done, ledger, checker, check_components=False).state == 'ready'
    assert not feasibility.surplus(done, ledger, checker, rows, derived)
    # A full page leaves the observation an Issue.
    full = copy.deepcopy(ELECTRICITY['rows'])
    full += [{**copy.deepcopy(full[0]), 'component': {**full[0]['component'], 'label': f'Year {n}'}}
             for n in range(12 - sum(r['page'] == 1 for r in full))]
    crowded = power_blueprint(snapshot, full)
    rows, _, added = completed(crowded, ledger)
    assert added == [] and len(rows) == len(full)
    assert any(i.requirement == "Observation 'People without access to electricity'"
               for i in req.evaluate(crowded, ledger, checker, check_components=False).issues)


@pytest.mark.usefixtures('catalog_types')
def test_a_using_date_profiled_at_the_grain_is_its_own_bucket():
    """Live run 20261025-123124: the planner drew the urban/rural area on `year` itself; its profile says
    every value starts a year, so the chart shows the defined grain without a derived bucket."""
    ledger, a, snapshot = power_assess()
    ledger = dropped(ledger, a, snapshot)
    area = {'question_id': 'q3', 'section_id': 's1', 'page': 1, 'note': '', 'status': 'ok', 'issue_ids': [], 'component': {
        'type': 'area', 'label': 'Rural vs. Urban Access Over Time', 'dimensions': [], 'date_dimension': 'year', 'breakdown': None,
        'metrics': [{'field': 'rural_pct', 'agg': 'avg'}, {'field': 'urban_pct', 'agg': 'avg'}], 'sort': None,
        'options': {'date_granularity': 'year'}}}
    rows = [*copy.deepcopy(ELECTRICITY['rows']), area]
    for starts, bound in (({'year': 'year'}, [len(rows) - 1]), ({}, []), ({'year': 'month'}, [])):
        current = copy.deepcopy(power_blueprint(snapshot, rows))
        for column in current['sources'][0]['columns']:
            if column['name'] == 'year':
                column['bucket_start'] = starts.get('year')
        verdicts = observation_verdicts(current, ledger)
        assert all(verdicts[o] == bound for o in ('o8', 'o9', 'o10', 'o11')), (starts, verdicts)
    # 24.10: the same area on page 2 is not on the reference page.
    elsewhere = [*rows[:-1], {**area, 'question_id': 'q5', 'section_id': 's2', 'page': 2}]
    verdicts = observation_verdicts(power_blueprint(snapshot, elsewhere), ledger)
    assert all(verdicts[o] == [] for o in ('o8', 'o9', 'o10', 'o11')), verdicts


@pytest.mark.usefixtures('catalog_types')
def test_removed_instructions_leave_code_added_rows_surplus():
    from dss.artifacts.models import Blueprint
    from dss.spec import feasibility
    ledger, a, snapshot = power_assess()
    ledger = dropped(ledger, a, snapshot)
    rows, derived, added = completed(power_blueprint(snapshot), ledger)
    blueprint = {**power_blueprint(snapshot)['blueprint'], 'rows': [r.model_dump() for r in rows],
                 'derived_fields': [f.model_dump() for f in derived]}
    removed, _, bare = power_assess([], snapshot=power_snapshot(''), ledger=ledger)
    checker = capabilities.Checker(capabilities.load_registry())
    bare = {**power_blueprint(bare), 'blueprint': blueprint}
    assert feasibility.surplus(bare, removed, checker, rows, derived) == {len(rows) - 2, len(rows) - 1}
    marked = feasibility.mark(bare, removed, checker, req.evaluate(bare, removed, checker, check_components=False))
    assert not any(feasibility.added(r) for r in marked.rows) and len(marked.rows) == len(ELECTRICITY['rows'])
    # Ordinary question-less controls are never code-added rows.
    assert not any(feasibility.added(r) for r in Blueprint.model_validate(blueprint).rows[:len(ELECTRICITY['rows'])])


def test_recreate_definitions_recompute_speed_with_24_observations_and_24_clauses(monkeypatch, record_property):
    """The 250 ms warm recomputation oracle holds with 24 observations and 24 definition clauses, on the
    catalog default (no DSS_ALLOWED_TYPES anywhere: the default re-reads no catalog per observation)."""
    from dss.spec import validate
    monkeypatch.delenv('DSS_ALLOWED_TYPES', raising=False)
    monkeypatch.setattr(validate, 'dotenv_values', lambda *_: {})
    items = [{**ELECTRICITY['items'][[1, 2, 5, 7][n % 4]], 'label': f'Chart {n}', 'metric_label': f'Metric {n}'} for n in range(24)]
    clauses = [f'Chart {n} = region, chart fixed_size_list.' if n % 4 == 0 else
               f'Metric {n} = AVG(access_pct), unit %, date grain year using year.' if n % 4 == 1 else
               f'Metric {n} = SUM(people_without_access), date grain year using year.' if n % 4 == 2 else
               f'Metric {n} = AVG(urban_pct) and AVG(rural_pct), unit %, chart area, date grain year using year.' for n in range(24)]
    sources = [ELECTRICITY['extraction'][o] for o in ('o2', 'o3', 'o6', 'o8')]
    extraction = {f'o{n + 1}': {**sources[n % 4], 'mappings': [{**m, 'label': f'Metric {n}'} for m in sources[n % 4]['mappings']],
                                'properties': [{'path': 'label', 'value': f'Chart {n}'}]} for n in range(24)}
    extraction['instructions'] = {'text': ' '.join(clauses), 'needs': [], 'mappings': []}
    snapshot = power_snapshot(' '.join(clauses), items)
    ledger, a = assess(snapshot, extraction)
    assert not [r for r in ledger.requirements if r.source.kind == 'reference'] and len(by_item(ledger)) == 24
    assert not [i for i in a.issues if i.resolution == 'unresolved'], [i.reason for i in a.issues]
    checker = capabilities.Checker(capabilities.load_registry())
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        req.evaluate(snapshot, ledger, checker, check_components=False)
        timings.append(time.perf_counter() - start)
    record_property('recompute_first_sample_s', timings[0])
    record_property('recompute_samples_s', json.dumps(timings))
    assert min(timings) < .250, timings


def year_case(expression='DATE_TRUNC(year, YEAR)', explicit=True):
    """Source-bound full-column proof plus a selected native axis; no metric-label identity."""
    from dss.artifacts.models import Blueprint
    snapshot = power_blueprint(power_snapshot())
    snapshot['sources'][0]['columns'] = copy.deepcopy(ELECTRICITY['columns'])
    date = next(c for c in snapshot['sources'][0]['columns'] if c['name'] == 'year')
    date.update(bucket_start='year', null_pct=0)
    qid = next(q['id'] for s in snapshot['outline']['sections'] for q in s['questions'] if q['selected'])
    component = dict(type='time_series', label='Overall trend without observation identity', dimensions=[],
        metrics=[{'field': 'access_pct', 'agg': 'avg'}], date_dimension='year_trunc', breakdown=None,
        sort={'field': 'year_trunc', 'order': 'asc'}, options={})
    snapshot['blueprint'].update(derived_fields=[dict(name='year_trunc', expression=expression,
        type='datetime', description='Planner year binding')], rows=[dict(question_id=qid, section_id='s1',
        page=1, component=component, note='', status='ok', issue_ids=[])])
    ledger = assess(snapshot, power_extraction())[0] if explicit else req.Ledger()
    return snapshot, ledger, Blueprint.model_validate(snapshot['blueprint'])


def normalized_year(snapshot, ledger, bp, protected=()):
    from dss.spec.feasibility import canonical_dates
    return canonical_dates(snapshot, ledger, capabilities.Checker(capabilities.load_registry()), bp, protected)


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('expression', ['DATE_TRUNC(year, YEAR)', ' date_trunc ( `year` , year ) - INTERVAL 0 DAY ',
                                      'DATE_TRUNC(year, YEAR) * 1'])
def test_canonical_year_reconstructs_whole_binding_and_sort_idempotently(expression, explicit):
    snapshot, ledger, bp = year_case(expression, explicit)
    after = normalized_year(snapshot, ledger, bp)
    assert after.derived_fields == []
    assert after.rows[0].component.date_dimension == after.rows[0].component.sort.field == 'year'
    assert after.rows[0].question_id == bp.rows[0].question_id and after.rows[0].note == bp.rows[0].note
    assert normalized_year(snapshot, ledger, after) == after
    assert bp.rows[0].component.date_dimension == 'year_trunc'  # no mutation


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('expression', ['DATE_TRUNC(year, YEAR) * 2', 'DATE_TRUNC(year, YEAR) + INTERVAL 0 DAY',
    'DATE_TRUNC(year, YEAR) - INTERVAL 1 DAY', 'DATE_TRUNC(year, MONTH)', 'CAST(DATE_TRUNC(year,YEAR) AS DATE)',
    'DATE_TRUNC(year, YEAR) * 1 + 0', "IF(TRUE, DATE_TRUNC(year,YEAR), NULL)", 'DATE_TRUNC(`year, YEAR)',
    'DATE_TRUNC(t0.year, YEAR)', 'DATE_TRUNC(year, YEAR);'])
def test_canonical_year_never_simplifies_other_sql(expression):
    snapshot, ledger, bp = year_case(expression)
    assert normalized_year(snapshot, ledger, bp) == bp


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('case', ['proof_missing', 'sample_only', 'null', 'wrong_type', 'wrong_grain', 'metric',
    'sort_only', 'protected', 'context', 'dependency', 'collision', 'option', 'not_selected', 'not_axis', 'conflicting_intent'])
def test_canonical_year_requires_current_proof_and_every_use(case):
    snapshot, ledger, bp = year_case(explicit=case not in ('not_selected', 'not_axis'))
    column = next(c for c in snapshot['sources'][0]['columns'] if c['name'] == 'year')
    protected = ()
    if case in ('proof_missing', 'sample_only'):
        column.pop('bucket_start')
        snapshot['date_starts'] = {'year': 'year'}  # stale name-only maps authorize nothing
    elif case == 'null':
        column['null_pct'] = 100
    elif case == 'wrong_type':
        column.update(type='datetime', bq_type='TIMESTAMP')
    elif case == 'wrong_grain':
        column['bucket_start'] = 'month'
    elif case == 'metric':
        bp.rows[0].component.metrics[0].field = 'year_trunc'
    elif case == 'sort_only':
        bp.rows[0].component.date_dimension = 'year'
    elif case == 'protected':
        protected = ('year_trunc',)
    elif case == 'context':
        snapshot['context']['derived_fields'] = [bp.derived_fields[0].model_dump()]
    elif case == 'dependency':
        bp.derived_fields.append(bp.derived_fields[0].model_copy(update={'name': 'other', 'expression': 'year_trunc'}))
    elif case == 'collision':
        snapshot['sources'][0]['columns'].append({**column, 'name': 'year_trunc'})
    elif case == 'option':
        bp.rows[0].component.options = {'row_dimensions': ['year_trunc']}
    elif case == 'not_selected':
        bp.rows[0].question_id = 'q_unknown'
    elif case == 'not_axis':
        bp.rows[0].component.type = 'bar'
        bp.rows[0].component.dimensions = ['year_trunc']
    elif case == 'conflicting_intent':
        # Same explicit date field, incompatible confirmed grain.
        changed = power_snapshot(ELECTRICITY['instructions'].replace('date grain year', 'date grain month'))
        snapshot['reference'], snapshot['incoming'] = changed['reference'], changed['incoming']
        ledger = assess(snapshot, power_extraction())[0]
    assert normalized_year(snapshot, ledger, bp, protected) == bp


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('explicit', [False, True])
def test_missing_year_alias_requires_explicit_binding_and_moves_all_date_slots(explicit):
    snapshot, ledger, bp = year_case(explicit=explicit)
    bp.derived_fields = []
    c = bp.rows[0].component
    c.type, c.date_dimension, c.dimensions, c.breakdown = 'bar', 'year_year', ['year_year'], 'year_year'
    c.sort.field = 'year_year'
    after = normalized_year(snapshot, ledger, bp)
    assert (after != bp) == explicit
    if explicit:
        c = after.rows[0].component
        assert (c.date_dimension, c.dimensions, c.breakdown, c.sort.field) == ('year', ['year'], 'year', 'year')
    bp.rows[0].component.date_dimension = 'some_unknown_alias'
    bp.rows[0].component.dimensions = []
    bp.rows[0].component.breakdown = None
    bp.rows[0].component.sort = None
    assert normalized_year(snapshot, ledger, bp) == bp


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('mode', ['style', None])
def test_canonical_year_does_not_change_other_reference_modes(mode):
    snapshot, ledger, bp = year_case()
    snapshot['reference'] = {**snapshot['reference'], 'mode': mode} if mode else None
    before = bp.model_dump_json()
    assert normalized_year(snapshot, ledger, bp).model_dump_json() == before


@pytest.mark.usefixtures('catalog_types')
def test_canonical_year_cannot_reuse_stale_observation_authorization():
    snapshot, ledger, bp = year_case()
    snapshot['reference']['instructions'] = ''
    snapshot['incoming'] = [s for s in snapshot['incoming'] if not s['id'].endswith(':instructions')]
    assert any(req.observation_stale(snapshot, r) for r in ledger.requirements)
    assert normalized_year(snapshot, ledger, bp) == bp


@pytest.mark.usefixtures('catalog_types')
def test_canonical_year_respects_grain_on_an_observation_with_another_issue():
    snapshot, ledger, bp = year_case(explicit=False)
    rid = snapshot['reference']['id']
    text = 'Monthly access = AVG(access_pct), date grain month using year.'
    snapshot['reference']['instructions'] = text
    snapshot['incoming'] = [req.Source(id=rid + ':instructions', kind='reference',
        text=text, reference_id=rid).model_dump()]
    r = req.Requirement(id='monthly', text='Monthly access with an unsupported behavior',
        source=req.Source(id=rid + ':monthly', kind='image', reference_id=rid,
            text=json.dumps(dict(kind='chart', label='Monthly access', metric_label='Monthly access',
                                 date_grain='month', aggregation='avg'))),
        needs=[{'capability': 'chart.time_series', 'fields': {'date_field': 'year'}},
               {'capability': 'unknown.monthly_behavior'}],
        mappings=[{'label': 'Monthly access', 'field': 'access_pct', 'aggregation': 'avg', 'date_grain': 'month'}])
    req._reconcile_observation(r, snapshot)
    ledger.requirements = [r]
    checker = capabilities.Checker(capabilities.load_registry())
    assert not r.mapping_conflicts and not req.observation_stale(snapshot, r)
    assert req.blueprint_observations(snapshot, ledger, checker) == []
    assert normalized_year(snapshot, ledger, bp) == bp


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('expression,dependent', [
    (r"CASE WHEN country = 'O\'Reilly' THEN year_trunc ELSE DATE '2000-01-01' END", True),
    (r'''CASE WHEN country = "O\"Reilly" THEN `year_trunc` ELSE DATE "2000-01-01" END''', True),
    (r"CONCAT('O\'Reilly year_trunc', country)", False),
])
def test_canonical_year_dependency_scan_handles_escaped_literals(expression, dependent):
    snapshot, ledger, bp = year_case()
    bp.derived_fields.append(bp.derived_fields[0].model_copy(update={'name': 'other', 'expression': expression}))
    after = normalized_year(snapshot, ledger, bp)
    assert (after == bp) == dependent
    assert ('year_trunc' in {f.name for f in after.derived_fields}) == dependent


# 25.8: unlabeled reference control binding (architecture.md#Unlabeled reference control binding).
UNLABELED = json.loads((Path(__file__).parent / 'data/recreate_unlabeled_control.json').read_text(encoding='utf-8'))
UNLABELED_INPUTS = Path(__file__).parents[1] / UNLABELED['provenance']['run']
REGION_SELECTOR = 'Region Selector: fixed_size_list on region (from your instructions)'
REGION = 'Region: dropdown on region (from your instructions)'


def unlabeled_snapshot(instructions=None, items=None, columns=None, mode='recreate'):
    """What inputs() returns for run 20261027-173624's reference (o5: the unlabeled region list)."""
    case = UNLABELED['case']
    rid, image = case['reference']['id'], case['reference']['image_id']
    text = case['instructions'] if instructions is None else instructions
    items = case['items'] if items is None else items
    incoming = [req.Source(id=rid + ':instructions', kind='reference', text=text, reference_id=rid).model_dump()] * bool(text)
    incoming += [req.Source(id=f'{rid}:{i["id"]}', kind='image', text=json.dumps(i, ensure_ascii=False), reference_id=rid,
                            image_id=image, item_id=i['id']).model_dump()
                 for i in items if mode == 'recreate' and (i['kind'] in ('chart', 'control', 'unknown') or i.get('metric_label'))]
    columns = case['sources'][0]['columns'] if columns is None else columns
    return {'sources': [{'id': 's', 'table': 'p.d.t', 'columns': [{k: c[k] for k in ('name', 'type', 'bq_type', 'date_like') if k in c}
                                                                for c in columns]}],
            'incoming': incoming, 'reference': {'id': rid, 'mode': mode, 'instructions': text, 'images': [{'id': image}],
                                                'interpretation': {'items': items}},
            'definitions': {}, 'spec': None, 'confirmed_kpis': case['context']['kpis']}


def unlabeled_assess(snapshot, ledger=None, requirements=None):
    """The run's extracted rows (or `requirements`) rechecked on `snapshot`, without a model call."""
    if ledger is None:
        ledger = req.Ledger(requirements=requirements or UNLABELED['case']['requirements']['requirements'])
        ledger.processed_sources = {s['id']: req.digest(s) for s in snapshot['incoming']}
    checker = capabilities.Checker(capabilities.load_registry())
    ledger = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    assessment = req.evaluate(snapshot, ledger, checker, check_components=False)
    ledger.assessment = assessment
    return ledger, assessment


def control_issues(ledger, assessment):
    """{item id: its control_field issue} of the controls."""
    owners = {r.text: r.source.item_id for r in ledger.requirements}
    return {owners[i.requirement]: i for i in assessment.issues if 'supplies control_field' in i.reason}


def decide_on(snapshot, ledger, *choices):
    """req.decide on the current assessment: (issue, alternative label, or None to drop) pairs."""
    checker = capabilities.Checker(capabilities.load_registry())
    decisions = [{'issue_id': issue.id, 'action': 'drop' if label is None else 'accept_alternative',
                  'alternative_id': None if label is None else next(a.id for a in issue.alternatives if a.label == label)}
                 for issue, label in choices]
    updated, assessment = req.decide(snapshot, ledger, checker, req.Decisions(assessment_id=ledger.assessment.id, decisions=decisions))
    updated.assessment = assessment
    return updated, assessment


def second_control(items, label=None, oid='o12'):
    """A copy of o5 (another unlabeled list, or a labeled one) and its extracted row."""
    item = {**next(i for i in items if i['id'] == 'o5'), 'id': oid, 'label': label}
    row = copy.deepcopy(next(r for r in UNLABELED['case']['requirements']['requirements'] if r['source']['item_id'] == 'o5'))
    rid, text = UNLABELED['case']['reference']['id'], json.dumps(item, ensure_ascii=False)
    row['id'], row['text'] = 'req_' + oid, text
    row['source'].update(id=f'{rid}:{oid}', item_id=oid, text=text)
    return item, row


def test_unlabeled_fixture_inputs_are_the_recorded_read_only_copies():
    import ast
    import hashlib
    tree = ast.parse((Path(__file__).parent / 'live/test_reference_design.py').read_text(encoding='utf-8'))
    [value] = [node.value for node in tree.body if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'INSTRUCTIONS']
    assert UNLABELED['case']['instructions'] == ast.literal_eval(value)
    if not UNLABELED_INPUTS.is_dir():
        pytest.skip('the run evidence (.blueprint/, git-ignored) is local to the machine that recorded it')
    for name, digest in UNLABELED['provenance']['sha256'].items():
        assert hashlib.sha256((UNLABELED_INPUTS / name).read_bytes()).hexdigest() == digest, name
    recorded = json.loads((UNLABELED_INPUTS / 'build/requirements.json').read_text(encoding='utf-8'))
    assert UNLABELED['case']['requirements']['requirements'] == recorded['requirements']


@pytest.mark.usefixtures('catalog_types')
def test_unlabeled_control_offers_instruction_clauses_then_fields():
    """25.8 block (run 20261027-173624): the region list o5 was extracted with `label: null`, so its
    control_field clarification had `alternatives: []` and nothing could bind it. Now code offers the
    unused instruction control clauses, then the catalog-valid fields; nothing applies itself."""
    assert UNLABELED['case']['before'] == {'status': 'needs_clarification', 'alternatives': [],
                                           'reason': 'Choose which field supplies control_field for Drop-down list control'}
    snapshot = unlabeled_snapshot()
    ledger, a = unlabeled_assess(snapshot)
    issue = control_issues(ledger, a)['o5']
    assert (issue.status, issue.reason) == ('needs_clarification', UNLABELED['case']['before']['reason'])
    assert issue.resolution == 'unresolved' and a.state == 'blocked'
    assert [x.label for x in issue.alternatives] == [
        REGION_SELECTOR, REGION, 'Country: dropdown on country (from your instructions)',
        # Field offers in name order, without the needs an instruction offer already carries (region, country).
        *[f'dropdown on {f}' for f in ('access_pct', 'people_without_access', 'rural_pct', 'urban_pct', 'year')]]
    assert len({x.id for x in issue.alternatives}) == len(issue.alternatives)
    # Deterministic: a recompute offers the same ids.
    again = control_issues(*unlabeled_assess(snapshot))['o5']
    assert [x.id for x in again.alternatives] == [x.id for x in issue.alternatives]
    # Every other issue is the run's own (the geo map), without alternatives.
    owners = {r.text: r.source.item_id for r in ledger.requirements}
    assert {owners[i.requirement] for i in a.issues} == {'o3', 'o5'} and all(not i.alternatives for i in a.issues if i is not issue)
    assert req.unused_definitions(snapshot, ledger) == ['Region Selector', 'Region', 'Country', 'Access to electricity', 'Urban', 'Rural']


@pytest.mark.usefixtures('catalog_types')
def test_accepted_clause_binds_through_the_decision_and_revalidates_against_the_instructions():
    snapshot = unlabeled_snapshot()
    ledger, a = unlabeled_assess(snapshot)
    issue = control_issues(ledger, a)['o5']
    decided, after = decide_on(snapshot, ledger, (issue, REGION_SELECTOR), *((i, None) for i in a.issues if i is not issue))
    assert after.state == 'ready', [i.reason for i in after.issues if i.resolution == 'unresolved']
    [record] = [d for d in decided.decisions if d.get('observation')]
    assert record['observation'] == 'o5' and record['alternative']['clause'] == 'Region Selector'
    assert record['alternative']['needs'] == [{'capability': 'control.fixed_size_list', 'value': None, 'fields': {'control_field': 'region'}}]
    # The decision is the provenance: the row's mappings, clarifications and meaning stay as extracted.
    row = next(r for r in decided.requirements if r.source.item_id == 'o5')
    assert row == next(r for r in ledger.requirements if r.source.item_id == 'o5') and not row.mappings
    checker = capabilities.Checker(capabilities.load_registry())
    [(r, needs, _)] = [o for o in req.blueprint_observations(snapshot, decided, checker) if o[0].source.item_id == 'o5']
    # The same control type and field a label match gives.
    assert req.observation_meaning(r, needs, []) == {'id': 'o5', 'kind': 'control', 'type': 'fixed_size_list', 'dimensions': ['region']}
    # A recompute (an explicit check) leaves the decision applying.
    rechecked, again = unlabeled_assess(snapshot, decided)
    assert again.state == 'ready' and control_issues(rechecked, again)['o5'].resolution == 'accepted_alternative'
    text = UNLABELED['case']['instructions']
    changes = {'removed': text.replace('Region Selector = region, chart fixed_size_list. ', ''),
               'changed field': text.replace('Region Selector = region,', 'Region Selector = country,'),
               'changed type': text.replace('chart fixed_size_list', 'chart dropdown')}
    for name, changed_text in changes.items():
        changed = unlabeled_snapshot(changed_text)
        relinked, blocked = unlabeled_assess(changed, decided.model_copy(deep=True))
        returned = control_issues(relinked, blocked)['o5']
        assert blocked.state == 'blocked' and returned.resolution == 'unresolved', name
        assert REGION_SELECTOR not in [x.label for x in returned.alternatives], name
        # The stored alternative's id is no longer offered.
        with pytest.raises(req.RunError) as refused:
            req.decide(changed, relinked, checker, req.Decisions(assessment_id=blocked.id, decisions=[
                {'issue_id': returned.id, 'action': 'accept_alternative', 'alternative_id': record['alternative']['id']}]))
        assert (refused.value.status_code, refused.value.message) == (422, 'Choose an offered alternative from this assessment'), name
        # Restoring the clause restores the binding.
        _, restored = unlabeled_assess(snapshot, relinked)
        assert restored.state == 'ready', name
    # A label match since: an observation now named "Region Selector" claims the clause.
    items = [{**i, 'label': 'Region Selector'} if i['id'] == 'o2' else i for i in UNLABELED['case']['items']]
    named = unlabeled_snapshot(items=items)
    relabeled = decided.model_copy(deep=True)
    for r in relabeled.requirements:
        if r.source.item_id == 'o2':
            r.text = r.source.text = json.dumps(next(i for i in items if i['id'] == 'o2'), ensure_ascii=False)
    relabeled.processed_sources = {s['id']: req.digest(s) for s in named['incoming']}
    relabeled, claimed = unlabeled_assess(named, relabeled)
    assert control_issues(relabeled, claimed)['o5'].resolution == 'unresolved'
    # An assessment id that is no longer current gets 409.
    with pytest.raises(req.RunError) as stale:
        req.decide(snapshot, rechecked, checker, req.Decisions(assessment_id=a.id, decisions=[
            {'issue_id': issue.id, 'action': 'drop', 'alternative_id': None}]))
    assert stale.value.status_code == 409


@pytest.mark.usefixtures('catalog_types')
def test_one_clause_binds_one_unlabeled_control():
    items, rows = copy.deepcopy(UNLABELED['case']['items']), copy.deepcopy(UNLABELED['case']['requirements']['requirements'])
    item, row = second_control(items)
    snapshot = unlabeled_snapshot(items=items + [item])
    ledger, a = unlabeled_assess(snapshot, requirements=rows + [row])
    issues = control_issues(ledger, a)
    # Both see the unused clause until one accepts it.
    assert all(REGION_SELECTOR in [x.label for x in issues[o].alternatives] for o in ('o5', 'o12'))
    with pytest.raises(req.RunError) as twice:
        decide_on(snapshot, ledger, (issues['o5'], REGION_SELECTOR), (issues['o12'], REGION_SELECTOR))
    assert (twice.value.status_code, twice.value.message) == (422, 'Bind the instruction clause Region Selector to one observation')
    decided, after = decide_on(snapshot, ledger, (issues['o5'], REGION_SELECTOR))
    issues = control_issues(decided, after)
    assert issues['o5'].resolution == 'accepted_alternative' and issues['o12'].resolution == 'unresolved'
    assert REGION_SELECTOR in [x.label for x in issues['o5'].alternatives]
    assert REGION_SELECTOR not in [x.label for x in issues['o12'].alternatives]
    # The clause an applying decision binds cannot be chosen for o12, even by o5's own alternative id.
    reused = next(x.id for x in issues['o5'].alternatives if x.label == REGION_SELECTOR)
    with pytest.raises(req.RunError) as bound:
        req.decide(snapshot, decided, capabilities.Checker(capabilities.load_registry()), req.Decisions(
            assessment_id=after.id, decisions=[{'issue_id': issues['o12'].id, 'action': 'accept_alternative', 'alternative_id': reused}]))
    assert bound.value.status_code == 422
    # A single candidate is still the user's decision: one unused clause and one field never bind on their own.
    region = [c for c in UNLABELED['case']['sources'][0]['columns'] if c['name'] == 'region']
    single = unlabeled_snapshot('Region Selector = region, chart fixed_size_list.', columns=region)
    lonely = control_issues(*unlabeled_assess(single))['o5']
    assert [x.label for x in lonely.alternatives] == [REGION_SELECTOR, 'dropdown on region'] and lonely.resolution == 'unresolved'
    silent = control_issues(*unlabeled_assess(unlabeled_snapshot('Urban = AVG(rural_pct), unit %.', columns=region)))['o5']
    assert [x.label for x in silent.alternatives] == ['dropdown on region'] and silent.resolution == 'unresolved'


@pytest.mark.usefixtures('catalog_types')
def test_missing_field_date_range_and_chart_clauses_are_not_offered():
    """A clause whose field is not in the schema, or typed date_range or a chart type, offers nothing here
    (unused clauses raise no issue of their own)."""
    text = ('Region Selector = province, chart fixed_size_list. Year Range = year, chart date_range. '
            'Region Bars = region, chart bar. Country = country.')
    ledger, a = unlabeled_assess(unlabeled_snapshot(text))
    issue = control_issues(ledger, a)['o5']
    assert [x.label for x in issue.alternatives][:1] == ['Country: dropdown on country (from your instructions)']
    assert not [x for x in issue.alternatives if '(from your instructions)' in x.label][1:]
    assert not any(i.reason.startswith(('Region Selector', 'Year Range', 'Region Bars')) for i in a.issues)


@pytest.mark.usefixtures('catalog_types')
def test_wide_schema_keeps_both_unlabeled_controls_visible_with_instruction_offers_only():
    columns = UNLABELED['case']['sources'][0]['columns'] + [
        {'name': f'segment_{n:02d}', 'type': 'string', 'bq_type': 'STRING', 'date_like': False} for n in range(20)]
    items, rows = copy.deepcopy(UNLABELED['case']['items']), copy.deepcopy(UNLABELED['case']['requirements']['requirements'])
    item, row = second_control(items)
    snapshot = unlabeled_snapshot(items=items + [item], columns=columns)
    ledger, a = unlabeled_assess(snapshot, requirements=rows + [row])
    assert not any(i.id == 'issue_scope' for i in a.issues)
    issues = control_issues(ledger, a)
    assert {o: [x.label.split(':')[0] for x in i.alternatives] for o, i in issues.items()} == {
        o: ['Region Selector', 'Region', 'Country'] for o in ('o5', 'o12')}
    # With the run's schema both issues' field offers fit the shared limit (8 + 8 of 20).
    narrow, b = unlabeled_assess(unlabeled_snapshot(items=items + [item]), requirements=rows + [row])
    assert [len(i.alternatives) for i in control_issues(narrow, b).values()] == [8, 8]
    # The instruction offers alone resolve both.
    decided, after = decide_on(snapshot, ledger, (issues['o5'], REGION_SELECTOR), (issues['o12'], REGION))
    assert all(i.resolution == 'accepted_alternative' for i in control_issues(decided, after).values())
    assert [d['alternative']['clause'] for d in decided.decisions] == ['Region Selector', 'Region']


@pytest.mark.usefixtures('catalog_types')
def test_labeled_controls_unlabeled_charts_and_other_modes_get_no_binding_offers():
    items, rows = copy.deepcopy(UNLABELED['case']['items']), copy.deepcopy(UNLABELED['case']['requirements']['requirements'])
    labeled, labeled_row = second_control(items, label='Year picker', oid='o13')
    ledger, a = unlabeled_assess(unlabeled_snapshot(items=items + [labeled]), requirements=rows + [labeled_row])
    assert control_issues(ledger, a)['o13'].alternatives == []  # a labeled control: label match or clarification, as before
    # An unlabeled chart observation (o2 without its label) gets no new offers.
    blank = [{**i, 'label': None} if i['id'] == 'o2' else i for i in items]
    text = json.dumps(next(i for i in blank if i['id'] == 'o2'), ensure_ascii=False)
    blank_rows = [{**r, 'text': text, 'source': {**r['source'], 'text': text}} if r['source']['item_id'] == 'o2' else r for r in rows]
    ledger, b = unlabeled_assess(unlabeled_snapshot(items=blank), requirements=blank_rows)
    owners = {r.text: r.source.item_id for r in ledger.requirements}
    assert all(not i.alternatives for i in b.issues if owners.get(i.requirement) != 'o5')
    # Style and data references, and builds without one: the o5 row is no reference observation there.
    checker = capabilities.Checker(capabilities.load_registry())
    for snapshot in (unlabeled_snapshot(mode='style'), unlabeled_snapshot(mode='data'), {**unlabeled_snapshot(), 'reference': None}):
        assert all(req._offers(r, f'need:{n}', snapshot, checker, ledger) == req._offers(r, f'need:{n}', snapshot, checker) == []
                   for r in ledger.requirements for n in range(len(r.needs)) if r.needs[n].capability.startswith('control.'))


@pytest.mark.usefixtures('catalog_types')
def test_binding_offers_recompute_within_budget(record_property):
    """24 observations (16 unlabeled controls) and 24 definition clauses (15 control clauses) within 250 ms warm."""
    items, rows = copy.deepcopy(UNLABELED['case']['items']), copy.deepcopy(UNLABELED['case']['requirements']['requirements'])
    rows = [r for r in rows if r['source']['item_id'] != 'o3']
    while len(rows) < 24:
        item, row = second_control(items, oid=f'o{len(items) + 1}')
        items.append(item)
        rows.append(row)
    clauses = [f'Picker {n} = {("region", "country")[n % 2]}' + (', chart fixed_size_list' if n % 3 == 0 else '') for n in range(12)]
    snapshot = unlabeled_snapshot(UNLABELED['case']['instructions'] + ' ' + '. '.join(clauses) + '.', items=items)
    assert len(req._surface_clauses(snapshot['reference']['instructions'])[0]) == 24
    ledger, a = unlabeled_assess(snapshot, requirements=rows)
    issues = control_issues(ledger, a)
    assert len(rows) == 24 and len(issues) == 16 and all(len(i.alternatives) == 15 for i in issues.values())
    assert not any(i.id == 'issue_scope' for i in a.issues)
    decided, _ = decide_on(snapshot, ledger, (issues['o5'], REGION_SELECTOR))
    checker = capabilities.Checker(capabilities.load_registry())
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        req.evaluate(snapshot, decided, checker, check_components=False)
        timings.append(time.perf_counter() - start)
    record_property('recompute_first_sample_s', timings[0])
    record_property('recompute_samples_s', json.dumps(timings))
    assert min(timings) < .250, timings


def unlabeled_build(blueprint_api, monkeypatch, polluted=False):
    """Run 20261027-173624's reference and extracted rows installed as a staged build, rechecked in code
    through the real gate; the planner answers with the fixture's reconstructed draft."""
    from types import SimpleNamespace
    from dss.artifacts.models import Context, Design, Outline
    from dss.render import background
    from dss.spec.models import TYPES
    from test_blueprint import artifact
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    case = UNLABELED['case']
    case = json.loads(json.dumps(case).replace(case['sources'][0]['id'], sid))
    source = case['sources'][0]
    for column in source['columns']:
        column['sample'] = []
    with app.state.db.connect() as conn:
        conn.execute('UPDATE sources SET columns_json=?, bq_table=?, kind=? WHERE id=?',
                     (json.dumps(source['columns']), source['bq_table'], 'synthetic', sid))
    artifact(folder, Context.model_validate(case['context']))
    artifact(folder, Outline.model_validate(case['outline']))
    artifact(folder, Design.model_validate(case['design']))
    reference = {'id': case['reference']['id'], 'mode': 'recreate', 'instructions': case['instructions'], 'summary': 'Saved reference',
                 'images': [{'id': case['reference']['image_id'], 'name': 'reference.png', 'file': 'reference_img_000000000000.png',
                             'mime_type': 'image/png', 'width': 1200, 'height': 900}],
                 'interpretation': {'mode': 'recreate', 'items': case['items'], 'aspect_ratio': 1.7196}}
    (folder / 'references.json').write_text(json.dumps(reference), encoding='utf-8')
    (folder / 'reference_img_000000000000.png').write_bytes(png())
    snapshot = req.inputs(app.state.db, bid, folder)
    ledger = req.Ledger.model_validate(case['requirements'])
    if polluted:
        # Feed the real worker boundary the recorded run-2 guess, adapted only to
        # this fixture's local source identity. It must not authorize the field.
        proposed = copy.deepcopy(UNLABELED['polluted']['mapped_surface_variant'])
        proposed['source'] = next(r for r in case['requirements']['requirements'] if r['source']['item_id'] == 'o5')['source']
        ledger.requirements = [req.Requirement.model_validate(proposed) if r.source.item_id == 'o5' else r
                               for r in ledger.requirements]
    ledger.processed_sources = {s['id']: req.digest(s) for s in snapshot['incoming']}
    ledger = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    checker = capabilities.Checker(capabilities.load_registry())
    req.save(folder, ledger, req.evaluate(snapshot, ledger, checker, check_components=False))
    # The one row repair (for the Location legend's page-1 gap): the planner returns its page-1 rows unchanged.
    repair = [r for r in case['draft']['rows'] if r['page'] == 1 and r['question_id'] in ('q1', 'q2', 'q3')]
    llm.replies = [json.dumps(case['draft']), json.dumps({'rows': repair})]
    from types import SimpleNamespace as Field
    bq.dry_run = lambda sql: bq.sql.append(sql) or [Field(name=f['name'], field_type='FLOAT', mode='NULLABLE')
                                                    for f in case['draft']['derived_fields']]
    bq.created, bq.deleted = [], []
    bq.create_view = lambda table, sql: bq.created.append(table)
    bq.delete_view = lambda table: bq.deleted.append(table) or True
    bq.aggregate = lambda sql: [{'year': '2011-01-01', 'region': 'Asia', 'country': 'Philippines', 'm0': 10, 'm1': 5}]
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height, scale=None: path.write_bytes(b'PNG'))
    monkeypatch.setattr(app.state.settings, 'defaults', app.state.settings.defaults.model_copy(update={'designed_pages': False}))
    return SimpleNamespace(client=client, app=app, bid=bid, folder=folder, llm=llm, bq=bq)


def owned_issues(build, assessment):
    """(observation item id, issue) of the unresolved issues: by requirement text, or a Blueprint
    observation issue's source evidence."""
    rows = req.load(build.folder).requirements
    owners = {r.text: r.source.item_id for r in rows} | {r.source.id: r.source.item_id for r in rows}
    return [(owners.get(i['requirement']) or next((owners[e] for e in i['evidence'] if e in owners), None), i)
            for i in assessment['issues'] if i['resolution'] == 'unresolved']


@pytest.mark.parametrize('polluted', [False, True])
def test_unlabeled_region_list_binds_by_clause_and_publishes(blueprint_api, monkeypatch, polluted):
    """The oracle: o5's issue offers the Region Selector clause first; accepting it with the approved geo map
    (and legend) drops makes the assessment ready, and accept publishes o5 as a page-1 fixed_size_list on
    region, its binding listed in feasibility.md. Recipe compiles; the fake engine finishes."""
    from test_blueprint import confirm
    from test_render import accept, executes
    from dss.spec.models import DashboardSpec
    build = unlabeled_build(blueprint_api, monkeypatch, polluted=polluted)
    url = f'/api/builds/{build.bid}'
    assessment = build.client.get(url + '/feasibility').json()
    pending = owned_issues(build, assessment)
    assert sorted({o for o, _ in pending}) == ['o3', 'o5'], pending
    [o5] = [i for o, i in pending if o == 'o5']
    assert o5['alternatives'][0]['label'] == REGION_SELECTOR and [a['label'] for a in o5['alternatives']][3:] == [
        f'dropdown on {f}' for f in ('access_pct', 'people_without_access', 'rural_pct', 'urban_pct', 'year')]
    decisions = [{'issue_id': o5['id'], 'action': 'accept_alternative', 'alternative_id': o5['alternatives'][0]['id']}]
    decisions += [{'issue_id': i['id'], 'action': 'drop', 'alternative_id': None} for o, i in pending if o == 'o3']
    stale = build.client.post(url + '/feasibility/decisions', json={'assessment_id': 'assessment_old', 'decisions': decisions})
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'feasibility_stale'
    decided = build.client.post(url + '/feasibility/decisions', json={'assessment_id': assessment['id'], 'decisions': decisions})
    assert decided.status_code == 200, decided.text
    assert build.client.get(url + '/feasibility').json()['state'] == 'ready'
    confirm(build.client, build.app, build.bid)
    assessment = build.client.get(url + '/feasibility').json()
    # Only the approved legend class may remain (o2, the "Location" bar): drop it explicitly.
    left = owned_issues(build, assessment)
    assert {o for o, _ in left} <= {'o2'}, [(o, i['reason']) for o, i in left]
    if left:
        dropped = build.client.post(url + '/feasibility/decisions', json={'assessment_id': assessment['id'], 'decisions': [
            {'issue_id': i['id'], 'action': 'drop', 'alternative_id': None} for _, i in left]})
        assert dropped.status_code == 200, dropped.text
        assessment = build.client.get(url + '/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    pages = {c.id: (p.index, c) for p in spec.pages for c in p.components}
    ledger = req.load(build.folder)
    row = next(r for r in ledger.requirements if r.source.item_id == 'o5')
    [bound] = [e['fulfilled_by'] for e in ledger.verification[row.id] if 'fulfilled_by' in e]
    assert bound and all(pages[c][0] == 1 and (pages[c][1].type, pages[c][1].field) == ('fixed_size_list', 'region') for c in bound), bound
    feasibility = (build.folder / 'docs/feasibility.md').read_text(encoding='utf-8')
    assert '## Decisions\n\n- o5 bound by clause Region Selector\n' in feasibility
    # A recompute after accept leaves the decision applying.
    _, rechecked = check(build.client, build.app, build.bid)
    assert rechecked['state'] == 'ready' and not rechecked['prototype_stale'], rechecked
    assert next(i for i in rechecked['issues'] if i['id'] == o5['id'])['resolution'] == 'accepted_alternative'
    executes(build.client, build.app, build.bid, monkeypatch)
    recipe = [json.loads(line) for line in (build.folder / 'recipe.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(op['op'] == 'add_control' and op['component_id'] in bound and op['control_type'] == 'fixed_size_list'
               and op['field'] == 'region' for op in recipe[1:])
    # Reload and a real version copy preserve the accepted proof, without carrying
    # a reusable assessment id. Recompute verifies the choice in the copied version.
    decisions = req.load(build.folder).decisions
    assert build.client.post(url + '/versions').status_code == 201
    copied = req.load(build.folder.parent / 'v2')
    assert copied.assessment is None and copied.decisions == decisions
    _, checked = check(build.client, build.app, build.bid)
    assert checked['state'] == 'ready', checked
    assert next(i for i in checked['issues'] if i['id'] == o5['id'])['resolution'] == 'accepted_alternative'


# 25.9: originally blank controls can only acquire a field through an explicit decision.
def polluted_row(mapped=False):
    polluted = UNLABELED['polluted']
    return req.Requirement.model_validate(polluted['mapped_surface_variant'] if mapped else next(
        r for r in polluted['requirements'] if r['source']['item_id'] == 'o5'))


def test_polluted_fixture_is_a_sanitized_read_only_run_copy():
    import hashlib
    polluted = UNLABELED['polluted']
    root = Path(__file__).resolve().parents[1] / polluted['provenance']['run']
    if not root.is_dir():
        pytest.skip('recorded evidence is local to its recording machine')
    for name, expected in polluted['provenance']['sha256'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    recorded = json.loads((root / 'build/requirements.json').read_text(encoding='utf-8'))['requirements']
    # Replace only local source identities, never semantic keys (Property.path).
    serialized = json.dumps(recorded, ensure_ascii=False)
    for old, new in polluted['provenance']['identity_replacements'].items():
        serialized = serialized.replace(old, new)
    assert polluted['requirements'] == json.loads(serialized)
    assert polluted_row().needs[0].fields == {'control_field': 'region'}
    assert json.loads(polluted_row().source.text)['label'] is None


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('mapped', [False, True])
@pytest.mark.parametrize('metric_label', [None, 'Region Selector'])
def test_worker_guesses_and_restored_surfaces_cannot_bind_or_claim_clauses(mapped, metric_label):
    snapshot = unlabeled_snapshot()
    row = polluted_row(mapped)
    item = json.loads(row.source.text)
    item['metric_label'] = metric_label
    row.source.text = json.dumps(item)
    # Unrelated unsupported behavior and explicit property requests stay intact.
    row.needs.append(capabilities.Need(capability='animation.temporal_playback'))
    if mapped:
        saved = json.loads(row.mapping_origins['surface'])
        saved['needs'].append(row.needs[-1].model_dump())
        row.mapping_origins['surface'] = json.dumps(saved)
    original = row.model_copy(deep=True)
    raw = req.Ledger(requirements=[row], processed_sources={s['id']: req.digest(s) for s in snapshot['incoming']})
    checker = capabilities.Checker(capabilities.load_registry())
    # A pure check cannot repair persisted guessed rows or leak them to planning.
    value = raw.model_dump()
    assert req.observation_stale(snapshot, row)
    assert req.evaluate(snapshot, raw, checker, check_components=False).state == 'blocked'
    assert req.blueprint_observations(snapshot, raw, checker) == []
    assert raw.model_dump() == value
    reconciled = req.merge(raw, snapshot, req.Extraction(requirements=[]))
    [clean] = reconciled.requirements
    assert clean.needs == [capabilities.Need(capability='control.dropdown'), row.needs[-1]]
    assert clean.mappings == [] and clean.mapping_origins == {}
    assert clean.properties == original.properties and clean.source == original.source
    assert 'Region Selector' in req.unused_definitions(snapshot, reconciled)
    issue = control_issues(reconciled, req.evaluate(snapshot, reconciled, checker))['o5']
    assert issue.resolution == 'unresolved' and issue.alternatives[0].label == REGION_SELECTOR
    assert req.blueprint_observations(snapshot, reconciled, checker) == []
    assert not req.observation_stale(snapshot, clean)
    assert req.merge(reconciled, snapshot, req.Extraction(requirements=[])) == reconciled
    assert raw.model_dump() == value


@pytest.mark.usefixtures('catalog_types')
def test_legacy_polluted_ready_proof_blocks_pure_reads_without_writes():
    snapshot, row = unlabeled_snapshot(), polluted_row()
    ledger = req.Ledger(requirements=[row], processed_sources={s['id']: req.digest(s) for s in snapshot['incoming']})
    checker = capabilities.Checker(capabilities.load_registry())
    ledger.assessment = req.Assessment(id='old_ready', state='ready', input_digest=req.input_digest(snapshot, ledger, checker))
    before = ledger.model_dump()
    for _ in range(2):
        current = req.get(snapshot, ledger, checker)
        assert current.state == 'blocked' and current.id is None
        assert any(i.id.startswith('obs_stale_') for i in current.issues)
        with pytest.raises(req.RunError, match='Feasibility changed'):
            req.require_current(snapshot, ledger, checker, 'old_ready')
    assert ledger.model_dump() == before


@pytest.mark.usefixtures('catalog_types')
def test_old_polluted_rows_block_read_recipe_and_run_until_explicit_check(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    case = UNLABELED['case']
    reference = {'id': case['reference']['id'], 'mode': 'recreate', 'instructions': case['instructions'],
                 'images': [{'id': case['reference']['image_id'], 'name': 'reference.png',
                             'file': 'reference_img_000000000000.png', 'mime_type': 'image/png', 'width': 1200, 'height': 900}],
                 'summary': 'Saved reference', 'interpretation': {'items': UNLABELED['polluted']['items'], 'aspect_ratio': 1.7196}}
    (folder / 'references.json').write_text(json.dumps(reference), encoding='utf-8')
    (folder / 'reference_img_000000000000.png').write_bytes(png())
    snapshot = req.inputs(app.state.db, bid, folder)
    ledger = req.Ledger(requirements=[polluted_row()])
    ledger.processed_sources = {s['id']: req.digest(s) for s in snapshot['incoming']}
    checker = capabilities.Checker(capabilities.load_registry())
    # Simulate an unmodified ready proof saved by the old reconciliation rule.
    req.save(folder, ledger, req.Assessment(id='legacy_ready', state='ready',
                                          input_digest=req.input_digest(snapshot, ledger, checker)))
    before = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT count(*) FROM traces').fetchone()[0]
    for _ in range(2):
        current = client.get(f'/api/builds/{bid}/feasibility').json()
        assert current['state'] == 'blocked' and any(i['id'].startswith('obs_stale_') for i in current['issues'])
        for endpoint in ('recipe', 'run'):
            response = client.post(f'/api/builds/{bid}/{endpoint}')
            assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    assert {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()} == before
    assert not app.state.engine_tasks and not app.state.agent_jobs.jobs
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces').fetchone()[0] == traces
    model = use_model(monkeypatch, app)
    _, checked = check(client, app, bid)
    assert model.calls == 0
    issue = control_issues(req.load(folder), req.Assessment.model_validate(checked))['o5']
    assert issue.resolution == 'unresolved' and issue.alternatives[0].label == REGION_SELECTOR
    assert req.load(folder).requirements[0].needs[0].fields == {}


@pytest.mark.usefixtures('catalog_types')
def test_polluted_decision_proof_is_never_reset_into_authorization():
    snapshot = unlabeled_snapshot()
    ledger, assessment = unlabeled_assess(snapshot)
    issue = control_issues(ledger, assessment)['o5']
    accepted, _ = decide_on(snapshot, ledger, (issue, REGION_SELECTOR))
    row = next(r for r in accepted.requirements if r.source.item_id == 'o5')
    row.mappings = [req.Mapping(label='Region Selector', field='region')]
    row.needs[0].fields['control_field'] = 'region'
    # An old decision referring to the polluted meaning is preserved as historical
    # proof; normalization must not re-sign it with the newly clean meaning.
    decision = next(d for d in accepted.decisions if d.get('observation'))
    decision['meaning'] = req.meaning(row)
    old = copy.deepcopy(accepted.decisions)
    repaired, assessment = unlabeled_assess(snapshot, accepted)
    assert repaired.decisions == old
    assert control_issues(repaired, assessment)['o5'].resolution == 'unresolved'


@pytest.mark.usefixtures('catalog_types')
def test_pre_enforcement_mapped_binding_cannot_own_a_clause_on_pure_reads():
    snapshot = unlabeled_snapshot()
    ledger, _ = unlabeled_assess(snapshot)
    row = next(r for r in ledger.requirements if r.source.item_id == 'o5')
    # Historically this direct-field mapping passed mapping_verdict and consumed
    # Region, while the missing-field issue still offered Region Selector. An API
    # decision could therefore have been saved against this unnormalized meaning.
    row.mappings = [req.Mapping(label='region', field='region')]
    checker = capabilities.Checker(capabilities.load_registry())
    assert req.mapping_verdict(row.mappings[0], row, req.schema(snapshot)) is None
    alternative = next(o for o in req._offers(row, 'need:0', snapshot, checker, ledger) if o['label'] == REGION_SELECTOR)
    needs = [capabilities.Need.model_validate(n) for n in alternative['needs']]
    legacy = {'requirement_id': row.id, 'meaning': req.meaning(row), 'slot': 'need:0',
              'action': 'accept_alternative', 'alternative': alternative,
              'prerequisites': req._prerequisites(snapshot, needs, row.mappings),
              'baseline': {}, 'applied': False, 'issue_id': 'legacy_issue', 'observation': 'o5'}
    ledger.decisions.append(legacy)
    item, other = second_control(UNLABELED['case']['items'])
    snapshot['reference']['interpretation']['items'].append(item)
    ledger.requirements.append(req.Requirement.model_validate(other))
    value = ledger.model_dump()
    assert req._choice(row, 'need:0', snapshot, ledger, checker) is None
    assert req._bound_clauses(ledger.requirements[-1], snapshot, ledger, checker) == set()
    offers = req._offers(ledger.requirements[-1], 'need:0', snapshot, checker, ledger)
    assert REGION_SELECTOR in [o['label'] for o in offers]
    assert req.evaluate(snapshot, ledger, checker).state == 'blocked'
    assert ledger.model_dump() == value
    repaired = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    assert repaired.decisions == [legacy]
    normalized = next(r for r in repaired.requirements if r.source.item_id == 'o5')
    assert req._choice(normalized, 'need:0', snapshot, repaired, checker) is None


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('clause', [False, True])
def test_clean_binding_proof_survives_reload_reconciliation_and_version_copy(tmp_path, monkeypatch, clause):
    snapshot = unlabeled_snapshot(None if clause else '')
    ledger, assessment = unlabeled_assess(snapshot)
    issue = control_issues(ledger, assessment)['o5']
    label = REGION_SELECTOR if clause else 'dropdown on region'
    ledger, _ = decide_on(snapshot, ledger, (issue, label), *((i, None) for i in assessment.issues if i is not issue))
    proof, rows = copy.deepcopy(ledger.decisions), [r.model_dump() for r in ledger.requirements]
    checker = capabilities.Checker(capabilities.load_registry())
    for _ in range(2):
        ledger, assessment = unlabeled_assess(snapshot, ledger)
        ledger = req.revalidate_decisions(snapshot, ledger, checker)
        assert assessment.state == 'ready'
        assert ledger.decisions == proof and [r.model_dump() for r in ledger.requirements] == rows
        req.save(tmp_path, ledger, assessment)
        ledger = req.load(tmp_path)
    destination = tmp_path / 'copy'
    destination.mkdir()
    monkeypatch.setattr(req, 'inputs', lambda *_: snapshot)
    req.copy_version(None, 'build', tmp_path, destination)
    copied = req.load(destination)
    assert copied.decisions == proof and copied.assessment is None
    copied, assessment = unlabeled_assess(snapshot, copied)
    assert assessment.state == 'ready' and copied.decisions == proof
    changed = copy.deepcopy(snapshot)
    region = next(c for c in changed['sources'][0]['columns'] if c['name'] == 'region')
    region['bq_type'], region['type'] = 'BYTES', 'BYTES'
    _, invalid = unlabeled_assess(changed, copied)
    assert control_issues(copied, invalid)['o5'].resolution == 'unresolved'
    assert copied.decisions == proof


@pytest.mark.usefixtures('catalog_types')
@pytest.mark.parametrize('operation', ['merge', 'evaluate', 'observation_stale', 'blueprint_observations',
                                      'revalidate_decisions', 'get', 'decide'])
def test_effective_allowlist_is_read_once_per_outer_operation(monkeypatch, operation):
    from dss.spec import validate
    snapshot = unlabeled_snapshot()
    ledger, assessment = unlabeled_assess(snapshot)
    checker = capabilities.Checker(capabilities.load_registry())
    calls = []
    monkeypatch.setattr(validate, 'dotenv_values', lambda path: calls.append(path) or {})
    if operation == 'merge':
        req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    elif operation == 'observation_stale':
        req.observation_stale(snapshot, next(r for r in ledger.requirements if r.source.item_id == 'o5'))
    elif operation == 'decide':
        issue = control_issues(ledger, assessment)['o5']
        req.decide(snapshot, ledger, checker, req.Decisions(assessment_id=assessment.id, decisions=[{
            'issue_id': issue.id, 'action': 'accept_alternative',
            'alternative_id': next(a.id for a in issue.alternatives if a.label == REGION_SELECTOR)}]))
    else:
        getattr(req, operation)(snapshot, ledger, checker)
    assert len(calls) <= 1, (operation, len(calls))
    assert req._operation_types.get() is None


def test_operation_allowlist_refreshes_env_file_default_and_empty_semantics(monkeypatch):
    from dss.spec import validate
    from dss.spec.models import TYPES
    snapshot = unlabeled_snapshot()
    file_config = {'DSS_ALLOWED_TYPES': ','.join(TYPES)}
    monkeypatch.delenv('DSS_ALLOWED_TYPES', raising=False)
    monkeypatch.setattr(validate, 'dotenv_values', lambda _: file_config.copy())
    checker = capabilities.Checker(capabilities.load_registry(), allowed=TYPES)
    ledger, _ = unlabeled_assess(snapshot)
    original = ledger.model_dump()
    def offers():
        assessment = req.evaluate(snapshot, ledger, checker)
        return [a.label for a in control_issues(ledger, assessment)['o5'].alternatives]
    wide = offers()
    assert REGION_SELECTOR in wide
    file_config['DSS_ALLOWED_TYPES'] = 'dropdown,unregistered'
    assert REGION_SELECTOR not in offers() and REGION in offers()
    monkeypatch.setenv('DSS_ALLOWED_TYPES', '')
    assert offers() == []
    monkeypatch.setenv('DSS_ALLOWED_TYPES', 'fixed_size_list')
    assert offers() == [REGION_SELECTOR]
    monkeypatch.delenv('DSS_ALLOWED_TYPES')
    file_config.clear()
    assert offers() == wide
    assert ledger.model_dump() == original
    # Exceptions cannot leave a scoped config cached for the next operation.
    monkeypatch.setenv('DSS_ALLOWED_TYPES', '')
    with pytest.raises(ValueError):
        req.merge(ledger, snapshot, req.Extraction(requirements=[extracted('unknown-source')]))
    assert req._operation_types.get() is None
    monkeypatch.delenv('DSS_ALLOWED_TYPES')
    assert offers() == wide
