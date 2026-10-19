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
        assert metadata["view"].endswith(f"dash_{build_id}_v1")
        refs = [p["docs"] for k, p in published if k == "docs.updated"]
        assert len(refs) == 1 and len(refs[0]) == 7


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
    assert [s["node"] for s in spans][:4] == ["router", "plan", "view", "spec"]
    assert spans[1]["input_tokens_estimate"] > 0 and spans[1]["sections"]
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
