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
    assert request.config.max_output_tokens == 4000
    assert BUDGETS["capability_check"] == 12000 and not request.config.tools
    assert "source_id" in json.dumps(request.config.response_json_schema)


@pytest.mark.parametrize("capability,status", [
    ("feature.telepathy", "unknown"), ("animation.temporal_playback", "unsupported_app"),
    ("extension.community_visualization", "unsupported_app"), ("control.fixed_size_list", "unsupported_app"),
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
    cap = next(c for c in raw["capabilities"] if c["id"] == "control.fixed_size_list")
    cap["native_product"]["status"] = "unsupported"
    registry = capabilities.Registry.model_validate(raw)
    monkeypatch.setattr("dss.harness.nodes.capability_check.load_registry", lambda: registry)
    monkeypatch.setattr("dss.api.feasibility.load_registry", lambda: registry)
    sid = user(app, bid, "A product-excluded feature")
    use_model(monkeypatch, app, extracted(sid, "control.fixed_size_list"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unsupported_product"


@pytest.mark.parametrize("count,finish,raw,error", [(4001, "STOP", None, None),
    (4000, "MAX_TOKENS", '{"requirements":[', None), (100, "MAX_TOKENS", '{"requirements":[', 'MAX_TOKENS')])
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
    assert a["state"] == "blocked" and "4k output" in a["issues"][0]["reason"] and model.calls == 1


def test_gemini_extraction_reserves_bounded_output_for_json(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, 'Show a bar')
    model = use_model(monkeypatch, app, extracted(sid))
    model.model = 'gemini-3.8-flash'
    check(client, app, bid)
    config = model.requests[0].config
    assert config.max_output_tokens == 4000
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
    vision = Capture(response=output(items=[]), requests=[])
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
    reported: int = 12001

    async def count_request_tokens(self, request):
        self.counted += 1
        return self.reported


@pytest.mark.parametrize("reported,generated,state", [(12000, 1, "ready"), (12001, 0, "blocked")])
def test_full_counted_input_budget(thin, monkeypatch, reported, generated, state):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show bar chart")
    model = Counted(response=json.dumps({"requirements": [extracted(sid)]}), reported=reported, requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == state and model.calls == generated and model.counted == 1
    if state == "blocked":
        assert "Reduce" in a["issues"][0]["reason"]


def test_oversize_assembly_blocks_without_call(thin, monkeypatch):
    client, app, bid, folder = thin
    user(app, bid, "x" * 60000)
    model = use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and model.calls == 0


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
    assert "20 issues" in a["issues"][0]["reason"] and len(req.load(folder).requirements) == 21


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


def test_deterministic_bounded_recompute_speed():
    checker = capabilities.Checker(capabilities.load_registry())
    ledger = req.Ledger(requirements=[req.Requirement(id=f"r{i}", source=req.Source(id="m", kind="message", text="bar"),
        text=f"Bar {i}", needs=[capabilities.Need(capability="chart.bar")]) for i in range(40)])
    snapshot = {"sources": [], "incoming": [], "reference": None, "definitions": {}, "spec": {
        "pages": [{"components": [{"id": f"c{i}", "type": "bar"} for i in range(24)]}]}}
    start = time.perf_counter()
    a = req.evaluate(snapshot, ledger, checker)
    assert a.state == "ready" and time.perf_counter() - start < .1


def test_bounded_recompute_speed_with_definitions():
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
    assert min(timings) < .1, timings


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
    items = [{'source_id': f'{rid}:{oid}', **e} for oid, e in extraction.items()
             if f'{rid}:{oid}' in {s['id'] for s in snapshot['incoming']}]
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


def test_recreate_bounded_recompute_speed():
    """24 observations (the interpretation maximum) reconcile with KPIs and instructions within 100 ms."""
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
    assert min(timings) < .1, timings


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


def test_decision_recompute_budget():
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
    assert a.state == "ready" and elapsed < .1


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
