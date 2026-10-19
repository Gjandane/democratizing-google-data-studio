import asyncio
import json
import pytest
import yaml
from dss.db import new_id
from dss.harness.nodes.intake import write_doc
from dss.harness.guardrails import RunError
from dss.harness.nodes.plan import Plan
from fakes import FakeLLM as BaseFakeLLM
from google.adk.models.llm_response import LlmResponse
from google.genai import types

class FakeLLM(BaseFakeLLM):
    async def generate_content_async(self, llm_request, stream=False):
        if (llm_request.config.response_json_schema or {}).get('title') == 'DashboardSpec':
            from test_spec_node import response_for
            self.calls += 1
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=json.dumps(response_for(llm_request)))]))
        else:
            async for event in super().generate_content_async(llm_request, stream):
                yield event


PLAN = {"brief": "Revenue for the director; assume monthly reporting.",
        "questions": [{"question": "How is revenue changing?", "priority": "high"}],
        "kpis": "Revenue: SUM(revenue), currency.",
        "fields": [{"name": "net", "sql": "`t0`.`revenue` * 0.9", "type": "FLOAT"}],
        "joins": [], "design": "Executive: concise scorecards and a monthly time series."}


class FakeBigQuery:
    def __init__(self, errors=0):
        self.errors, self.dry_runs, self.views = errors, [], []

    def dry_run(self, sql):
        self.dry_runs.append(sql)
        if len(self.dry_runs) <= self.errors:
            raise ValueError("BigQuery: unknown column missing")

    def create_view(self, table, sql):
        self.views.append((table, sql))

    def delete_view(self, table):
        self.views[:] = [(name, sql) for name, sql in self.views if name != table]

    def aggregate(self, sql):
        return [{'m0': 100}]


@pytest.fixture(autouse=True)
def offline_background(monkeypatch):
    monkeypatch.setattr('dss.render.background.capture',
        lambda html, path, width, height: path.write_bytes(b'PNG'))


class RepairLLM(FakeLLM):
    async def generate_content_async(self, llm_request, stream=False):
        if (llm_request.config.response_json_schema or {}).get('title') == 'DashboardSpec':
            async for event in super().generate_content_async(llm_request, stream):
                yield event
            return
        self.calls += 1
        plan = dict(PLAN)
        if self.calls == 1:
            plan["fields"] = [{"name": "net", "sql": "`t0`.`missing`", "type": "FLOAT"}]
        else:
            context = llm_request.config.system_instruction
            assert "BigQuery: unknown column missing" in context
            assert "`t0`.`missing`" in context
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(plan))]))


def seed(app, build_id):
    app.state.settings.update({"gcp_project_id": "project"})
    config = app.state.settings.get()
    source = {"bq_table": "project.data.sales", "columns": [
        {"name": "date", "type": "date", "bq_type": "DATE", "sample": []},
        {"name": "revenue", "type": "number", "bq_type": "FLOAT", "sample": []}]}
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='interview' WHERE id=?", (build_id,))
        conn.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)",
                     (new_id("s"), build_id, "bigquery", "sales", source["bq_table"], 2, json.dumps(source["columns"])))
    docs = config.data_dir / "builds" / build_id / "v1/docs"
    docs.mkdir(parents=True)
    write_doc(docs / "data-profile.md", {"type": "BigQuery Table", "sources": [source]}, "# Profile")
    return docs


def events(app, build_id):
    with app.state.db.connect() as conn:
        return [(r[0], json.loads(r[1])) for r in conn.execute(
            "SELECT kind,payload_json FROM events WHERE build_id=? ORDER BY rowid", (build_id,))]


@pytest.mark.parametrize("errors", [0, 1, 2])
async def test_plan_docs_and_repair(client, app, build_id, monkeypatch, errors):
    docs = seed(app, build_id)
    fake = FakeLLM(response=json.dumps(PLAN))
    service = FakeBigQuery(errors)
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    app.state.bigquery_factory = lambda config: service
    assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is False
    assert client.post(f"/api/builds/{build_id}/plan").status_code == 202
    for _ in range(300):
        if not app.state.engine_tasks:
            break
        await asyncio.sleep(.01)
    assert not app.state.engine_tasks
    assert fake.calls == (2 if errors == 0 else (3 if errors == 1 else 2))
    assert len(service.dry_runs) == (1 if errors == 0 else 2)
    published = events(app, build_id)
    final = published[-1][1]
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT * FROM traces").fetchall()
        assert len(traces) == 1
        assert traces[0]["status"] == ("error" if errors == 2 else "ok")
    if errors == 2:
        assert final["status"] == "error"
        assert "BigQuery: unknown column missing" in final["error"]
        assert client.get(f"/api/builds/{build_id}").json()["stage"] == "interview"
        assert not service.views
        assert not (docs / "brief.md").exists()
    else:
        assert final["status"] == "ok"
        assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'prototype'
        assert ('stage.changed', {'stage': 'prototype'}) in published
        assert any(k == 'prototype.updated' for k, _ in published)
        assert len(service.views) == 1
        expected = {"index.md": "Index", "log.md": "Log", "data-profile.md": "BigQuery Table",
            "brief.md": "Dashboard Brief", "questions.md": "Business Questions",
            "kpis.md": "KPI Definitions", "derived-fields.md": "Derived Fields",
            "design.md": "Design Direction", "decisions.md": "Design Decisions"}
        for filename, kind in expected.items():
            metadata = yaml.safe_load((docs / filename).read_text().split("---", 2)[1])
            assert metadata["type"] == kind
        metadata = yaml.safe_load((docs / "derived-fields.md").read_text().split("---", 2)[1])
        assert metadata["fields"] == PLAN["fields"]
        assert metadata["view"].endswith(f"dash_{build_id}_v1_{traces[0]['run_id']}")
        refs = [p["docs"] for k, p in published if k == "docs.updated"]
        assert len(refs) == 1 and len(refs[-1]) == 8
        assert any(d['path'] == 'feasibility.md' for d in refs[-1])


async def test_plan_wrong_stage(client, app, build_id):
    assert client.post(f"/api/builds/{build_id}/plan").status_code == 409
    assert client.post("/api/builds/missing/plan").status_code == 404


async def test_repair_changes_sql(client, app, build_id):
    seed(app, build_id)
    model, service = RepairLLM(), FakeBigQuery(1)
    await app.state.harness.run("plan", build_id,
        {"config": app.state.settings.get(), "factory": lambda config: service}, llm=model)
    assert model.calls == 3
    assert "`t0`.`missing`" in service.dry_runs[0]
    assert "`t0`.`revenue` * 0.9" in service.views[0][1]


class RecordingLLM(FakeLLM):
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request.model_copy(deep=True))
        async for event in super().generate_content_async(llm_request, stream):
            yield event


async def test_provider_request_uses_json_schema(client, app, build_id):
    seed(app, build_id)
    model = RecordingLLM(response=json.dumps(PLAN), requests=[])
    await app.state.harness.run("plan", build_id,
        {"config": app.state.settings.get(), "factory": lambda config: FakeBigQuery()}, llm=model)
    plan, spec = model.requests
    for request, title in ((plan, "Plan"), (spec, "DashboardSpec")):
        assert request.config.response_json_schema["title"] == title
        assert request.config.response_schema is None
        assert request.config.response_mime_type == "application/json"
    # The provider receives the strict schema; nothing is converted or loosened.
    assert plan.config.response_json_schema == Plan.model_json_schema()
    assert plan.config.response_json_schema["additionalProperties"] is False
    assert [c.parts[0].text for c in plan.contents] == ["Write the dashboard plan."]
    with app.state.db.connect() as conn:
        trace = conn.execute("SELECT * FROM traces").fetchone()
    spans = json.loads(trace["spans_json"])
    assert [s["node"] for s in spans][:6] == ["router", "capability_check", "assess_capabilities", "plan", "view", "spec"]
    assert spans[3]["input_tokens_estimate"] > 0 and spans[3]["sections"]
    assert trace["input_tokens"] >= 5 and trace["output_tokens"] >= 2


@pytest.mark.parametrize("response", ["not json", '{"brief":"test-key",', json.dumps({**PLAN, "brief": "test-key"}),
    json.dumps({**PLAN, "extra": "field"}), json.dumps({**PLAN, "questions": [{"question": "Q?", "priority": "urgent"}]}),
    json.dumps({**PLAN, "fields": [{"name": "Bad Name", "sql": "1", "type": "FLOAT"}]})])
async def test_invalid_or_unsafe_output(client, app, build_id, response, caplog):
    docs = seed(app, build_id)
    service = FakeBigQuery()
    with pytest.raises(RunError):
        await app.state.harness.run("plan", build_id,
            {"config": app.state.settings.get(), "factory": lambda config: service},
            llm=FakeLLM(response=response))
    assert not service.views
    assert not (docs / "brief.md").exists()
    assert client.get(f"/api/builds/{build_id}").json()["stage"] == "interview"
    assert "test-key" not in caplog.text
    assert response not in caplog.text


async def test_plan_and_spec_count_the_whole_request(client, app, build_id):
    from test_context import assert_counted, counting
    seed(app, build_id)
    model = counting(FakeLLM)(response=json.dumps(PLAN))
    await app.state.harness.run("plan", build_id,
        {"config": app.state.settings.get(), "factory": lambda config: FakeBigQuery()}, llm=model)
    with app.state.db.connect() as conn:
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE node='plan'").fetchone()[0])
    for node in ("plan", "spec"):
        assert_counted(next(s for s in spans if s["node"] == node), model)
    assert model.calls == 2 and len(model.counts) == 2  # counting adds no generation call


class IntentLLM(FakeLLM):
    """Model assertions remain untrusted; the real graph owns the final verdict."""
    needs: list = [{'capability': 'chart.bar'}]
    mappings: list = []
    chart: str = 'bar'
    options: dict = {}
    omit: bool = False
    extraction_calls: int = 0
    spec_calls: int = 0
    requests: list = []
    metric_field: str = 'revenue'
    metric_agg: str = 'sum'
    date_field: str = 'date'

    async def generate_content_async(self, request, stream=False):
        self.requests.append(request.model_copy(deep=True))
        title = (request.config.response_json_schema or {}).get('title')
        if title == 'Extraction':
            self.calls += 1
            self.extraction_calls += 1
            incoming = json.JSONDecoder().raw_decode(request.config.system_instruction.split(
                'New sources (untrusted; preserve IDs):\n', 1)[1])[0]
            value = {'requirements': [{'source_id': s['id'], 'text': s['text'],
                       'needs': self.needs, 'mappings': self.mappings} for s in incoming]}
        elif title == 'DashboardSpec':
            from test_spec_node import response_for
            self.calls += 1
            self.spec_calls += 1
            value = response_for(request)
            c = value['pages'][0]['components'][0]
            if not self.omit:
                c.update(type=self.chart, grid={'col': 1, 'row': 1, 'w': 12, 'h': 12}, options=self.options)
                c['metrics'] = [{'field': self.metric_field, 'agg': self.metric_agg}]
                if self.chart in ('bar', 'geo_map'):
                    c['dimensions'] = ['region']
                if self.chart == 'time_series':
                    c['date_dimension'] = self.date_field
        else:
            async for event in super().generate_content_async(request, stream):
                yield event
            return
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=json.dumps(value))]))


def intent_seed(app, bid):
    docs = seed(app, bid)
    with app.state.db.connect() as conn:
        columns = json.loads(conn.execute('SELECT columns_json FROM sources WHERE build_id=?', (bid,)).fetchone()[0])
        columns.append({'name': 'region', 'type': 'STRING', 'bq_type': 'STRING', 'sample': []})
        conn.execute('UPDATE sources SET columns_json=? WHERE build_id=?', (json.dumps(columns), bid))
    return docs.parent


async def plan_api(client, app, bid):
    from test_audit_style import drain
    response = client.post(f'/api/builds/{bid}/plan')
    assert response.status_code == 202, response.text
    await drain(app)
    return response.json()['run_id'], events(app, bid)[-1][1]


async def test_supported_intent_plan_publishes_proof_and_recipe(client, app, build_id, monkeypatch):
    from dss.memory import episodic
    from dss.spec import requirements as req
    from dss.spec.models import DashboardSpec
    from dss.recipe.compiler import compile_recipe
    folder = intent_seed(app, build_id)
    sid = episodic.save(app.state.db, build_id, 'user', 'Show sum revenue by region in a bar chart')['id']
    fake = IntentLLM(response=json.dumps(PLAN), mappings=[{'label': 'Revenue', 'field': 'revenue', 'aggregation': 'sum'}])
    service = FakeBigQuery()
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    app.state.bigquery_factory = lambda config: service
    run, final = await plan_api(client, app, build_id)
    assert final['status'] == 'ok' and fake.extraction_calls == fake.spec_calls == 1
    assert len(service.views) == 1
    a = client.get(f'/api/builds/{build_id}/feasibility').json()
    assert a['state'] == 'ready' and not a['prototype_stale']
    ledger = req.load(folder)
    assert ledger.requirements[0].source.id == sid and ledger.verification
    plan_request = next(r for r in fake.requests if r.config.response_json_schema['title'] == 'Plan')
    assert ledger.requirements[0].id in plan_request.config.system_instruction
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text())
    ops = [json.loads(line) for line in compile_recipe(spec, 1).split('\n')[1:-1]]
    assert any(op['op'] == 'add_chart' and op['chart_type'] == 'bar' and op['metrics'] == [{'field': 'revenue', 'agg': 'sum'}] for op in ops)
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces WHERE run_id=?', (run,)).fetchone()[0] == 1


@pytest.mark.parametrize('case', ['missing', 'option', 'option_missing', 'animation', 'render'])
async def test_candidate_failure_preserves_prior_dashboard(client, app, build_id, monkeypatch, case):
    from dss.memory import episodic
    from dss.spec import requirements as req
    folder = intent_seed(app, build_id)
    service = FakeBigQuery()
    fake = IntentLLM(response=json.dumps(PLAN))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    app.state.bigquery_factory = lambda config: service
    assert (await plan_api(client, app, build_id))[1]['status'] == 'ok'
    before = {name: (folder / name).read_bytes() for name in ('spec.json', 'prototype.html', 'background_p1.png', 'aggregate-cache.json')}
    previous_views = list(service.views)
    fake = IntentLLM(response=json.dumps(PLAN), omit=case == 'missing')
    if case in ('option', 'option_missing'):
        fake.needs = [{'capability': 'chart.bar'}, {'capability': 'option.bar.stacked', 'value': True}]
        fake.options = {'stacked': 'true'} if case == 'option' else {}
    if case == 'animation':
        fake.needs = [{'capability': 'chart.geo_map', 'fields': {'geo_field': 'region'}}]
        fake.chart = 'geo_map'
        fake.options = {'geo_type': 'region', 'animate': True}
        with app.state.db.connect() as conn:
            columns = json.loads(conn.execute('SELECT columns_json FROM sources WHERE build_id=?', (build_id,)).fetchone()[0])
            columns[-1]['type'] = columns[-1]['bq_type'] = 'GEOGRAPHY'
            conn.execute('UPDATE sources SET columns_json=? WHERE build_id=?', (json.dumps(columns), build_id))
    if case == 'render':
        monkeypatch.setattr('dss.render.background.capture', lambda *a: (_ for _ in ()).throw(RuntimeError('render failure')))
    episodic.save(app.state.db, build_id, 'user', 'Show a bar chart with the requested behavior')
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    run, final = await plan_api(client, app, build_id)
    assert final['status'] == 'error'
    assert fake.extraction_calls == 1 and fake.spec_calls == (1 if case == 'render' else 3)
    assert service.views == previous_views
    assert all((folder / name).read_bytes() == data for name, data in before.items())
    assert client.get(f'/api/builds/{build_id}/prototype').status_code == 200
    if case != 'render':
        assert not any(kind == 'prototype.updated' for kind, _ in events(app, build_id)[-3:])
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces WHERE run_id=?', (run,)).fetchone()[0] == 1


@pytest.mark.parametrize('image', [False, True])
async def test_unchecked_plan_extracts_mixed_unsupported_before_view(client, app, build_id, monkeypatch, image):
    from dss.memory import episodic
    from dss.spec import references
    from test_references import output, item, png
    from test_audit_style import STYLE, drain
    folder = intent_seed(app, build_id)
    service = FakeBigQuery()
    if image:
        # The real reference endpoint persists code-owned item provenance first.
        monkeypatch.setattr(references, 'decode', lambda images: None)
        interpretation = output(items=[item(label='Animated GPS', candidate='geo_map', metric=None, unit=None, aggregation=None)])
        monkeypatch.setattr(app.state.models, 'llm_for', lambda node: BaseFakeLLM(response=interpretation))
        response = client.post(f'/api/builds/{build_id}/reference-images', data={'mode': 'recreate'},
                               files=[('files', ('map.png', png(), 'image/png'))])
        assert response.status_code == 202
        await drain(app)
    else:
        episodic.save(app.state.db, build_id, 'user', 'Show a bar chart and animate GPS points along a route')
    fake = IntentLLM(response=json.dumps(PLAN), needs=[{'capability': 'chart.bar'}, {'capability': 'animation.temporal_playback'}])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    app.state.bigquery_factory = lambda config: service
    run, final = await plan_api(client, app, build_id)
    assert final['status'] == 'error' and fake.extraction_calls == 1 and fake.spec_calls == 0
    assert not service.dry_runs and not service.views
    a = client.get(f'/api/builds/{build_id}/feasibility').json()
    assert a['state'] == 'blocked' and a['issues'][0]['status'] == 'unsupported_app'
    from dss.spec import requirements as req
    assert req.load(folder).requirements[0].source.kind == ('image' if image else 'message')
    assert client.get(f'/api/builds/{build_id}/messages').json()[-1]['role'] == 'assistant'
    assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'interview'


async def test_explicit_metric_clarification_keeps_meaning_through_plan(client, app, build_id, monkeypatch):
    from test_interview import wait_done
    from dss.spec import requirements as req
    folder = intent_seed(app, build_id)
    with app.state.db.connect() as conn:
        columns = json.loads(conn.execute('SELECT columns_json FROM sources WHERE build_id=?', (build_id,)).fetchone()[0])
        columns.extend([{'name': n, 'type': 'number', 'bq_type': 'FLOAT', 'sample': []} for n in ('gross_sales', 'net_sales')])
        conn.execute('UPDATE sources SET columns_json=? WHERE build_id=?', (json.dumps(columns), build_id))
    needs = [{'capability': 'chart.time_series', 'fields': {'date_field': 'date'}}]
    fake = IntentLLM(needs=needs, mappings=[{'label': 'Revenue', 'field': None, 'aggregation': 'avg', 'unit': 'USD', 'date_grain': 'month'}])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    result = client.post(f'/api/builds/{build_id}/messages', json={'text': 'Show Revenue trend: average USD by month'})
    assert result.status_code == 202
    await wait_done(app)
    assert client.get(f'/api/builds/{build_id}/feasibility').json()['state'] == 'blocked'
    original = req.load(folder).requirements[0]
    fake.mappings = [{'label': 'Revenue', 'field': 'net_sales'}]
    # The ordinary conversational response after successful clarification.
    fake.response = 'The Revenue definition is clear.'
    clarified = client.post(f'/api/builds/{build_id}/messages', json={'text': 'Revenue means net_sales'})
    assert clarified.status_code == 202
    await wait_done(app)
    a = client.get(f'/api/builds/{build_id}/feasibility').json()
    assert a['state'] == 'ready', a
    ledger = req.load(folder)
    old = next(r for r in ledger.requirements if r.id == original.id)
    assert old.source == original.source and old.clarifications[0].id == clarified.json()['message_id']
    assert old.mappings[0].model_dump() == {'label': 'Revenue', 'field': 'net_sales', 'aggregation': 'avg', 'unit': 'USD', 'date_grain': 'month'}
    plan = {**PLAN, 'fields': [{'name': 'month_date', 'sql': 'DATE_TRUNC(`t0`.`date`, MONTH)', 'type': 'DATE'}]}
    fake = IntentLLM(response=json.dumps(plan), needs=needs, chart='time_series', metric_field='net_sales', metric_agg='avg', date_field='month_date')
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    _, final = await plan_api(client, app, build_id)
    assert final['status'] == 'ok', final
    assert fake.extraction_calls == 0 and fake.spec_calls == 1
    assert 'DATE_TRUNC' in service.views[0][1]
    spec = json.loads((folder / 'spec.json').read_text())
    component = spec['pages'][0]['components'][0]
    assert component['metrics'] == [{'field': 'net_sales', 'agg': 'avg'}]
    assert component['date_dimension'] == 'month_date'
    assert client.get(f'/api/builds/{build_id}/feasibility').json()['state'] == 'ready'


async def test_plan_rechecks_changed_allowlist_before_view(client, app, build_id, monkeypatch):
    from dss.memory import episodic
    from dss.spec import requirements as req
    folder = intent_seed(app, build_id)
    sid = episodic.save(app.state.db, build_id, 'user', 'Show a bar chart')['id']
    snapshot, checker = req.inputs(app.state.db, build_id, folder), req.capabilities.Checker(req.capabilities.load_registry())
    ledger = req.merge(req.Ledger(), snapshot, req.Extraction(requirements=[req.Extracted(source_id=sid, text='Show a bar chart', needs=[{'capability': 'chart.bar'}])]))
    req.save(folder, ledger, req.evaluate(snapshot, ledger, checker))
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    monkeypatch.setenv('DSS_ALLOWED_TYPES', 'scorecard')
    response = client.post(f'/api/builds/{build_id}/plan')
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    assert not service.views and not service.dry_runs and not app.state.engine_tasks


async def test_plan_rechecks_after_awaited_dry_run(client, app, build_id, monkeypatch):
    from dss.memory import episodic
    folder = intent_seed(app, build_id)
    fake = IntentLLM(response=json.dumps(PLAN))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    baseline = FakeBigQuery()
    app.state.bigquery_factory = lambda config: baseline
    assert (await plan_api(client, app, build_id))[1]['status'] == 'ok'
    before = {name: (folder / name).read_bytes() for name in ('spec.json', 'prototype.html')}
    episodic.save(app.state.db, build_id, 'user', 'Show a bar chart')
    class Narrowing(FakeBigQuery):
        def dry_run(self, sql):
            super().dry_run(sql)
            monkeypatch.setenv('DSS_ALLOWED_TYPES', 'scorecard')
    service = Narrowing()
    app.state.bigquery_factory = lambda config: service
    run, final = await plan_api(client, app, build_id)
    assert final['status'] == 'error'
    assert len(service.dry_runs) == 1 and not service.views and fake.spec_calls == 1
    assert client.get(f'/api/builds/{build_id}/feasibility').json()['state'] == 'blocked'
    assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'interview'
    assert all((folder / name).read_bytes() == data for name, data in before.items())
    assert client.get(f'/api/builds/{build_id}/messages').json()[-1]['role'] == 'assistant'
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT error FROM traces WHERE run_id=?', (run,)).fetchone()[0] == 'feasibility_blocked'
