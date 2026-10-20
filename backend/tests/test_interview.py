import asyncio
import json
from pathlib import Path
import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from dss.harness.guardrails import RunError
from dss.harness.context import interview_context
from dss.memory import episodic
from fakes import FakeLLM as BaseFakeLLM


class FakeLLM(BaseFakeLLM):
    extraction_calls: int = 0
    extra_capability: str | None = None
    ambiguous: bool = False
    extracted_source_ids: list[str] = []
    empty_needs: bool = False
    contexts: list[str] = []

    async def generate_content_async(self, llm_request, stream=False):
        if (llm_request.config.response_json_schema or {}).get("title") != "Extraction":
            self.contexts.append(str(llm_request.config.system_instruction))
        if (llm_request.config.response_json_schema or {}).get("title") == "Extraction":
            self.calls += 1
            self.extraction_calls += 1
            context = llm_request.config.system_instruction
            sources, _ = json.JSONDecoder().raw_decode(context.split("New sources (untrusted; preserve IDs):\n", 1)[1])
            requirements = [{"source_id": source["id"], "text": source["text"],
                             "needs": [] if self.empty_needs else [{"capability": "chart.scorecard"}]} for source in sources]
            self.extracted_source_ids.extend(source["id"] for source in sources)
            for item in requirements:
                if self.extra_capability:
                    item["needs"].append({"capability": self.extra_capability})
                if self.ambiguous:
                    item["mappings"] = [{"label": "Revenue", "field": "gross_sales", "aggregation": "sum"}]
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps({"requirements": requirements}))]))
            return
        async for event in super().generate_content_async(llm_request, stream):
            yield event


class ReadyLLM(FakeLLM):
    interview_calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        if (llm_request.config.response_json_schema or {}).get("title") == "Extraction":
            async for event in super().generate_content_async(llm_request, stream):
                yield event
            return
        self.calls += 1
        self.interview_calls += 1
        if self.interview_calls == 1:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
                function_call=types.FunctionCall(name="mark_ready_for_plan", args={}))]))
        else:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="The dashboard direction is ready.")]))


class StreamingLLM(FakeLLM):
    async def generate_content_async(self, llm_request, stream=False):
        assert stream is True
        text = "Which revenue decision should this dashboard support for your team?"
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text[:40])]), partial=True)
        if self.release:
            await self.release.wait()
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text[40:])]), partial=True)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


class BracesLLM(FakeLLM):
    async def generate_content_async(self, llm_request, stream=False):
        if (llm_request.config.response_json_schema or {}).get("title") == "Extraction":
            async for event in super().generate_content_async(llm_request, stream):
                yield event
            return
        assert "Compare {revenue}" in llm_request.config.system_instruction
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Which region matters most?")]))


def events(app, build_id):
    with app.state.db.connect() as conn:
        return [(r[0], json.loads(r[1])) for r in conn.execute(
            "SELECT kind,payload_json FROM events WHERE build_id=? ORDER BY rowid", (build_id,))]


async def wait_done(app):
    for _ in range(200):
        if not app.state.engine_tasks:
            return
        await asyncio.sleep(.01)
    pytest.fail("background action did not finish")


async def test_start_and_turn(client, app, build_id, monkeypatch):
    fake = FakeLLM(response="How should revenue guide your decisions?")
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    result = client.post(f"/api/builds/{build_id}/interview/start")
    assert result.status_code == 202
    await wait_done(app)
    assert client.get(f"/api/builds/{build_id}").json()["stage"] == "interview"
    reply = client.post(f"/api/builds/{build_id}/messages", json={"text": "Help our sales director"})
    assert reply.status_code == 202
    await wait_done(app)
    history = client.get(f"/api/builds/{build_id}/messages").json()
    assert [m["role"] for m in history] == ["assistant", "user", "assistant"]
    assert history[1]["id"] == reply.json()["message_id"] and history[1]["node"] is None
    fixture = json.loads((Path(__file__).parents[2] / "contracts/fixtures/api/messages.json").read_text())
    for actual, expected in zip(history, fixture):
        assert {k: type(v) for k, v in actual.items()} == {k: type(v) for k, v in expected.items()}
    kinds = [kind for kind, _ in events(app, build_id)]
    assert kinds.count("message.delta") == kinds.count("message.done") == 2
    assert kinds.index("message.delta") < kinds.index("message.done")
    with app.state.db.connect() as conn:
        rows = conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 2 and all(row["status"] == "ok" for row in rows)
        assert [s["node"] for s in json.loads(rows[0]["spans_json"])] == ["router", "capability_check", "assess_capabilities", "interview", "guardrail"]
    assert fake.extraction_calls == 1


async def test_ready_tool(client, app, build_id, monkeypatch):
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: ReadyLLM())
    assert client.post(f"/api/builds/{build_id}/interview/start").status_code == 202
    await wait_done(app)
    assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is True
    published = events(app, build_id)
    assert [p for kind, p in published if kind == "build.updated"][0]["build"]["ready_for_plan"] is True
    assert "mark_ready_for_plan" not in json.dumps(published)
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT tool_calls FROM traces").fetchone()[0] == 1
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: FakeLLM(response="Direction refined."))
    client.post(f"/api/builds/{build_id}/messages", json={"text": "Use monthly totals"})
    await wait_done(app)
    assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is True


@pytest.mark.parametrize("fake", [FakeLLM(fail=True), FakeLLM(response="test-key"), FakeLLM(response="mark_ready_for_plan")])
async def test_failure_is_guarded(client, app, build_id, monkeypatch, fake, caplog):
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    client.post(f"/api/builds/{build_id}/interview/start")
    await wait_done(app)
    assert client.get(f"/api/builds/{build_id}").json()["stage"] == "connect"
    assert client.get(f"/api/builds/{build_id}/messages").json() == []
    assert not any(k.startswith("message.") for k, _ in events(app, build_id))
    assert events(app, build_id)[-1][1]["status"] == "error"
    assert "sensitive content" not in caplog.text and "test-key" not in caplog.text
    assert not app.state.harness.active_builds


def test_wrong_stage_and_validation(client, app, build_id):
    assert client.get("/api/builds/missing/messages").status_code == 404
    assert client.post(f"/api/builds/{build_id}/messages", json={"text": "Hi"}).status_code == 409
    assert client.post(f"/api/builds/{build_id}/messages", json={"text": " "}).status_code == 422


async def test_concurrency(client, app, build_id):
    started, release = asyncio.Event(), asyncio.Event()
    app.state.harness.active_builds.add(build_id)
    task = asyncio.create_task(app.state.harness.run("interview", build_id,
        {"config": app.state.settings.get(), "text": "Start", "start": True},
        llm=FakeLLM(started=started, release=release), reserved=True))
    await asyncio.wait_for(started.wait(), 3)
    assert client.post(f"/api/builds/{build_id}/interview/start").status_code == 409
    release.set()
    await task


def test_context_profile_skills_history(client, app, build_id):
    folder = app.state.settings.get().data_dir / "builds" / build_id / "v1/docs"
    folder.mkdir(parents=True)
    (folder / "data-profile.md").write_text("---\ntype: BigQuery Table\n---\nrevenue, region, order_date", encoding="utf-8")
    for i in range(15):
        episodic.save(app.state.db, build_id, "user", f"Old message {i}")
    context = interview_context(app.state.db, app.state.settings.get(), build_id, "Current request")
    assert "revenue, region, order_date" in context and "# Executive" in context
    assert '"Old message 0"' not in context and '"Old message 14"' in context
    assert context.index("# Interview") < context.index("Data profile") < context.index("Chat history")


async def test_delta_before_generation_finishes(client, app, build_id, monkeypatch):
    received, release = asyncio.Event(), asyncio.Event()
    original = app.state.bus.publish
    async def publish(bid, kind, payload):
        if kind == "message.delta":
            received.set()
        await original(bid, kind, payload)
    monkeypatch.setattr(app.state.bus, "publish", publish)
    task = asyncio.create_task(app.state.harness.run("interview", build_id,
        {"config": app.state.settings.get(), "text": "Start", "start": True}, llm=StreamingLLM(release=release)))
    try:
        await asyncio.wait_for(received.wait(), 3)
        assert not task.done()
        assert not any(kind == "message.done" for kind, _ in events(app, build_id))
    finally:
        release.set()
        await task
    deltas = [p["text"] for k, p in events(app, build_id) if k == "message.delta"]
    saved = episodic.messages(app.state.db, build_id)[0]
    assert len(deltas) >= 2 and "".join(deltas) == saved["text"]


async def test_literal_braces(client, app, build_id):
    episodic.save(app.state.db, build_id, "user", "Compare {revenue}")
    result = await app.state.harness.run("interview", build_id,
        {"config": app.state.settings.get(), "text": "Compare {revenue}", "start": True}, llm=BracesLLM())
    assert result["reply"] == "Which region matters most?"


@pytest.mark.parametrize("capability,status", [("animation.temporal_playback", "unsupported_app"),
                                                ("feature.telepathy", "unknown"),
                                                (None, "needs_clarification")])
async def test_message_capability_gate(client, app, build_id, monkeypatch, capability, status):
    from test_plan import seed, FakeBigQuery
    from dss.spec import requirements as req

    seed(app, build_id)
    if capability is None:
        with app.state.db.connect() as conn:
            conn.execute("UPDATE sources SET columns_json=? WHERE build_id=?", (json.dumps([
                {"name": "gross_sales", "type": "number", "bq_type": "FLOAT", "sample": []},
                {"name": "net_sales", "type": "number", "bq_type": "FLOAT", "sample": []},
                {"name": "date", "type": "date", "bq_type": "DATE", "sample": []}]), build_id))
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET ready_for_plan=1 WHERE id=?", (build_id,))
    fake = FakeLLM(extra_capability=capability, ambiguous=capability is None, response="Which definition should we use?")
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    message = "Show Revenue" if capability is None else "Show a Revenue scorecard and animate GPS points along a route"
    response = client.post(f"/api/builds/{build_id}/messages", json={"text": message})
    assert response.status_code == 202
    await wait_done(app)
    # 14.1: the blocked assessment does not end the turn; the interviewer explains it.
    assert fake.extraction_calls == 1 and fake.calls == 2
    assert fake.extracted_source_ids == [response.json()["message_id"]]
    assessment = client.get(f"/api/builds/{build_id}/feasibility").json()
    assert assessment["state"] == "blocked"
    assert status in [issue["status"] for issue in assessment["issues"]]
    assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is False
    folder = app.state.settings.get().data_dir / "builds" / build_id / "v1"
    ledger = req.load(folder)
    assert ledger.requirements[0].source.id == response.json()["message_id"]
    history = client.get(f"/api/builds/{build_id}/messages").json()
    assert history[-1]["role"] == "assistant" and history[-1]["text"] == "Which definition should we use?"
    issues = fake.contexts[-1].split("Unresolved feasibility issues", 1)[1]
    assert all(issue["reason"] in issues for issue in assessment["issues"])
    if status == "unsupported_app":
        assert "Time series using date" in issues
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT * FROM traces WHERE build_id=?", (build_id,)).fetchall()
    assert len(traces) == 1 and traces[0]["status"] == "ok"
    assert [span["node"] for span in json.loads(traces[0]["spans_json"])][:4] == ["router", "capability_check", "assess_capabilities", "interview"]
    assert events(app, build_id)[-1][1]["status"] == "ok"
    blocked = client.post(f"/api/builds/{build_id}/plan")
    assert blocked.status_code == 409
    detail = blocked.json()["error"]["detail"]
    assert detail["assessment_id"] == assessment["id"]
    current = client.get(f"/api/builds/{build_id}/feasibility").json()
    assert detail["assessment_id"] == current["id"]
    assert set(detail["issue_ids"]) == {issue["id"] for issue in current["issues"] if issue["resolution"] == "unresolved"}
    assert fake.calls == 2 and not service.views and not service.dry_runs


@pytest.mark.parametrize('text,ready', [('Help our sales director', True), ('For the sales team', True),
                                      ('Help our sales director and animate GPS points', False),
                                      ('Help our sales director. Telepathic chart.', False)])
async def test_audience_metadata_full_source_only(client, app, build_id, monkeypatch, text, ready):
    from test_plan import seed, FakeBigQuery, FakeLLM as PlanLLM, PLAN
    from dss.spec import requirements as req
    seed(app, build_id)
    fake = ReadyLLM(empty_needs=True)
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    response = client.post(f'/api/builds/{build_id}/messages', json={'text': text})
    assert response.status_code == 202
    await wait_done(app)
    a = client.get(f'/api/builds/{build_id}/feasibility').json()
    assert a['state'] == ('ready' if ready else 'blocked')
    assert client.get(f'/api/builds/{build_id}').json()['ready_for_plan'] is ready
    # The interviewer runs either way; its early readiness call cannot bypass the block.
    assert fake.extraction_calls == 1 and fake.interview_calls == 2
    folder = app.state.settings.get().data_dir / 'builds' / build_id / 'v1'
    ledger = req.load(folder)
    assert ledger.requirements[0].source.id == response.json()['message_id']
    if ready:
        assert ledger.verification[ledger.requirements[0].id][0]['status'] == 'context'
        fake = FakeLLM(response='The scorecard scope is clear.')
        monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
        client.post(f'/api/builds/{build_id}/messages', json={'text': 'Show a Revenue scorecard'})
        await wait_done(app)
        model = PlanLLM(response=json.dumps(PLAN))
        monkeypatch.setattr(app.state.models, 'llm_for', lambda node: model)
        app.state.bigquery_factory = lambda config: FakeBigQuery()
        assert client.post(f'/api/builds/{build_id}/plan').status_code == 202
        await wait_done(app)
        assert events(app, build_id)[-1][1]['status'] == 'ok'


@pytest.mark.parametrize("forbidden", ["test-key", "mark_ready_for_plan"])
async def test_split_forbidden_stream(client, app, build_id, forbidden):
    from dss.harness.nodes.interview import ReplyStream
    stream = ReplyStream(app.state.harness, build_id, "r_stream")
    await stream.append("Safe preface. " * 4 + forbidden[:3])
    with pytest.raises(RunError):
        await stream.append(forbidden[3:])
    published = "".join(p["text"] for k, p in events(app, build_id) if k == "message.delta")
    assert forbidden not in published and forbidden[:3] not in published


class ScriptLLM(BaseFakeLLM):
    """Extraction scripted by exact source text; the interviewer tries readiness once per turn."""
    script: dict = {}
    extraction_calls: int = 0
    interview_calls: int = 0
    contexts: list[str] = []
    ready_results: list[bool] = []

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        if (llm_request.config.response_json_schema or {}).get("title") == "Extraction":
            self.extraction_calls += 1
            sources = json.JSONDecoder().raw_decode(llm_request.config.system_instruction.split(
                "New sources (untrusted; preserve IDs):\n", 1)[1])[0]
            items = [{**item, "source_id": s["id"]} for s in sources for item in self.script[s["text"]]]
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps({"requirements": items}))]))
            return
        self.interview_calls += 1
        self.contexts.append(str(llm_request.config.system_instruction))
        answered = [p.function_response for p in llm_request.contents[-1].parts or [] if p.function_response]
        if not answered:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
                function_call=types.FunctionCall(name="mark_ready_for_plan", args={}))]))
            return
        self.ready_results.append(answered[0].response["ready_for_plan"])
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"Interview reply {self.interview_calls}.")]))


AUDIENCE = "The audience is sales executives."
MIXED = ("The audience is sales executives. Track total revenue, order count, quantity sold and sales trends "
         "using only the uploaded columns.")
SCORECARD = [{"capability": "chart.scorecard"}]
TREND = [{"capability": "chart.time_series", "fields": {"date_field": "order_date"}}]
MIXED_SCRIPT = [
    {"text": AUDIENCE, "needs": []},
    {"text": "Track total revenue using only the uploaded columns", "needs": SCORECARD,
     "mappings": [{"label": "revenue", "field": "revenue", "aggregation": "sum"}]},
    {"text": "Track order count", "needs": SCORECARD, "mappings": [{"label": "order count", "field": None}]},
    {"text": "Track quantity sold", "needs": SCORECARD, "mappings": [{"label": "quantity sold", "field": "quantity"}]},
    {"text": "Track sales trends", "needs": TREND, "mappings": [{"label": "sales trend", "field": None}]}]
ANSWERS = [  # Three successive explicit answers, each resolving one earlier mapping.
    ("Order count is COUNT(DISTINCT order_id).", [{"text": "Order count is COUNT(DISTINCT order_id).", "needs": [],
      "mappings": [{"label": "order count", "field": "order_id", "aggregation": "count_distinct"}]}]),
    ("Quantity sold is SUM(quantity).", [{"text": "Quantity sold is SUM(quantity).", "needs": SCORECARD,
      "mappings": [{"label": "quantity sold", "field": "quantity"}]}]),
    ("Sales trend is SUM(revenue) by month of order_date.", [{"text": "Sales trend is SUM(revenue) by month of order_date.",
      "needs": TREND, "mappings": [{"label": "sales trend", "field": "revenue", "aggregation": "sum", "date_grain": "month"}]}])]
SALES = {"order_id": "STRING", "order_date": "DATE", "revenue": "FLOAT", "quantity": "INTEGER"}


def sales_seed(app, build_id, **columns):
    from test_plan import seed
    seed(app, build_id)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE sources SET columns_json=? WHERE build_id=?", (json.dumps([
            {"name": name, "type": "date" if kind == "DATE" else "number" if kind in ("FLOAT", "INTEGER") else "text",
             "bq_type": kind, "sample": []} for name, kind in columns.items()]), build_id))
    return app.state.settings.get().data_dir / "builds" / build_id / "v1"


async def say(client, app, build_id, text):
    response = client.post(f"/api/builds/{build_id}/messages", json={"text": text})
    assert response.status_code == 202, response.text
    await wait_done(app)
    run = [p for kind, p in events(app, build_id) if kind == "run.finished"][-1]
    assert run["run_id"] == response.json()["run_id"] and run["status"] == "ok", run
    history = client.get(f"/api/builds/{build_id}/messages").json()
    assert history[-2]["id"] == response.json()["message_id"] and history[-1]["role"] == "assistant"
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM traces WHERE run_id=?", (run["run_id"],)).fetchone()[0] == 1
    return response.json()["message_id"], client.get(f"/api/builds/{build_id}/feasibility").json()


def audience_issues(assessment):
    return [i for i in assessment["issues"] if "audience" in i["requirement"].lower()]


@pytest.mark.parametrize("needs", [[], [{"capability": "unknown.unclassified"}]])
async def test_standalone_audience_is_context(client, app, build_id, monkeypatch, needs):
    from dss.spec import requirements as req
    folder = sales_seed(app, build_id, **SALES)
    fake = ScriptLLM(script={AUDIENCE: [{"text": AUDIENCE, "needs": needs}]})
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    sid, a = await say(client, app, build_id, AUDIENCE)
    assert a["state"] == "ready" and not a["issues"], a
    assert fake.extraction_calls == 1 and fake.ready_results == [True]
    assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is True
    row = req.load(folder).requirements[0]
    assert row.source.id == sid and row.text == AUDIENCE
    assert req.load(folder).verification[row.id][0]["status"] == "context"


async def test_mixed_audience_and_incomplete_metrics_continue_the_interview(client, app, build_id, monkeypatch):
    from dss.spec import requirements as req
    from test_plan import FakeBigQuery
    folder = sales_seed(app, build_id, **SALES)
    fake = ScriptLLM(script={MIXED: MIXED_SCRIPT})
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    sid, a = await say(client, app, build_id, MIXED)
    assert a["state"] == "blocked" and not audience_issues(a), a
    assert {i["status"] for i in a["issues"]} == {"needs_clarification"}
    # The early readiness call is refused and the interviewer sees the open definitions.
    assert fake.ready_results == [False] and fake.extraction_calls == 1
    assert "Define order count" in fake.contexts[-1] and "Define sales trend" in fake.contexts[-1]
    build = client.get(f"/api/builds/{build_id}").json()
    assert build["stage"] == "interview" and build["ready_for_plan"] is False
    ledger = req.load(folder)
    assert len(ledger.requirements) == 5 and {r.source.id for r in ledger.requirements} == {sid}
    audience = next(r for r in ledger.requirements if r.text == AUDIENCE)
    assert ledger.verification[audience.id][0]["status"] == "context"
    # Direct plan, recipe and run stay gated with no side effects.
    plan = client.post(f"/api/builds/{build_id}/plan")
    assert plan.status_code == 409 and plan.json()["error"]["code"] == "feasibility_blocked"
    for endpoint in ("recipe", "run"):
        assert client.post(f"/api/builds/{build_id}/{endpoint}").status_code == 409
    assert not service.views and not service.dry_runs and not app.state.engine_tasks
    assert not (folder / "spec.json").exists() and not (folder / "recipe.jsonl").exists()
    assert fake.calls == 3  # one extraction and two interviewer calls; the gates call no model


async def test_three_answers_resolve_definitions_without_losing_intent(client, app, build_id, monkeypatch):
    from dss.spec import requirements as req
    from test_plan import FakeBigQuery
    folder = sales_seed(app, build_id, **SALES)
    fake = ScriptLLM(script={MIXED: MIXED_SCRIPT, **dict(ANSWERS)})
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    app.state.bigquery_factory = lambda config: FakeBigQuery()
    first, a = await say(client, app, build_id, MIXED)
    original = {r.id: r for r in req.load(folder).requirements}
    open_issues = [len(a["issues"])]
    for i, (text, _) in enumerate(ANSWERS):
        sid, a = await say(client, app, build_id, text)
        assert fake.extraction_calls == i + 2  # one extraction per message
        open_issues.append(len([x for x in a["issues"] if x["resolution"] == "unresolved"]))
        ready = client.get(f"/api/builds/{build_id}").json()["ready_for_plan"]
        assert ready is (i == len(ANSWERS) - 1) and a["state"] == ("ready" if ready else "blocked")
        assert not audience_issues(a)
    assert open_issues == [3, 2, 1, 0] and fake.ready_results == [False, False, False, True]
    ledger = req.load(folder)
    # Definitions refine the original rows: same IDs, sources and needs, plus provenance.
    assert {r.id for r in ledger.requirements} == set(original)
    rows = {m.label: (r, m) for r in ledger.requirements for m in r.mappings}
    assert rows["order count"][1].model_dump() == {"label": "order count", "field": "order_id", "unit": None,
                                                   "aggregation": "count_distinct", "date_grain": None}
    assert rows["quantity sold"][1].aggregation == "sum"  # code read SUM(quantity) from the answer
    assert (rows["sales trend"][1].field, rows["sales trend"][1].date_grain) == ("revenue", "month")
    assert rows["revenue"][1].aggregation == "sum" and not rows["revenue"][0].clarifications
    for label in ("order count", "quantity sold", "sales trend"):
        r = rows[label][0]
        assert r.source.id == first and r.needs == original[r.id].needs and len(r.clarifications) == 1


@pytest.mark.parametrize("aggregation", ["count", None])
async def test_count_versus_distinct_count_is_never_guessed(client, app, build_id, monkeypatch, aggregation):
    sales_seed(app, build_id, **SALES)
    text = "Show the order count."
    fake = ScriptLLM(script={text: [{"text": text, "needs": SCORECARD,
        "mappings": [{"label": "order count", "field": "order_id", "aggregation": aggregation}]}],
        "Order count is COUNT(order_id).": [{"text": "Order count is COUNT(order_id).", "needs": [],
        "mappings": [{"label": "order count", "field": "order_id", "aggregation": "count_distinct"}]}]})
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    _, a = await say(client, app, build_id, text)
    assert a["state"] == "blocked"
    # A model proposal that contradicts the explicit COUNT(...) cannot resolve it.
    _, a = await say(client, app, build_id, "Order count is COUNT(order_id).")
    assert a["state"] == "blocked" and client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is False


async def test_gross_net_ambiguity_requires_an_explicit_choice(client, app, build_id, monkeypatch):
    from dss.spec import requirements as req
    folder = sales_seed(app, build_id, order_date="DATE", gross_sales="FLOAT", net_sales="FLOAT")
    revenue = [{"label": "Revenue", "field": "gross_sales", "aggregation": "sum"}]
    fake = ScriptLLM(script={
        "Show total Revenue": [{"text": "Show total Revenue", "needs": SCORECARD, "mappings": revenue}],
        "Use whichever revenue column is standard.": [{"text": "Use whichever revenue column is standard.",
            "needs": SCORECARD, "mappings": [{"label": "Revenue", "field": "gross_sales"}]}],
        "Revenue means net_sales.": [{"text": "Revenue means net_sales.", "needs": SCORECARD,
                                      "mappings": [{"label": "Revenue", "field": "net_sales"}]}]})
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    for text in ("Show total Revenue", "Use whichever revenue column is standard."):
        _, a = await say(client, app, build_id, text)
        assert a["state"] == "blocked" and all("Confirm which field defines Revenue" in i["reason"] for i in a["issues"])
        assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is False
    _, a = await say(client, app, build_id, "Revenue means net_sales.")
    assert a["state"] == "ready", a
    assert {m.field for r in req.load(folder).requirements for m in r.mappings} == {"net_sales"}
    assert fake.ready_results == [False, False, True]
    # After resolution, the existing supported planning path still works.
    from test_plan import IntentLLM, FakeBigQuery, PLAN, plan_api
    planner = IntentLLM(response=json.dumps({**PLAN, "fields": []}), chart="scorecard", metric_field="net_sales")
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: planner)
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    _, final = await plan_api(client, app, build_id)
    assert final["status"] == "ok", final
    assert planner.extraction_calls == 0 and len(service.views) == 1
    assert client.get(f"/api/builds/{build_id}/feasibility").json()["state"] == "ready"


@pytest.mark.parametrize("text,script,status", [
    (AUDIENCE + " Animate GPS points along a route.",
     [{"text": AUDIENCE, "needs": []}, {"text": "Animate GPS points along a route", "needs": [{"capability": "animation.temporal_playback"}]}],
     "unsupported_app"),
    (AUDIENCE + " Add a telepathic chart.", [{"text": AUDIENCE, "needs": []}, {"text": "Add a telepathic chart", "needs": []}], "unknown"),
    # The extractor drops the request: code keeps the whole message as an unknown row.
    (AUDIENCE + " Animate GPS points along a route.", [{"text": AUDIENCE, "needs": []}], "unknown")])
async def test_audience_never_hides_unsupported_or_unknown_requests(client, app, build_id, monkeypatch, text, script, status):
    from dss.spec import requirements as req
    folder = sales_seed(app, build_id, **SALES)
    fake = ScriptLLM(script={text: script})
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    sid, a = await say(client, app, build_id, text)
    assert a["state"] == "blocked" and [i["status"] for i in a["issues"]] == [status], a
    assert not audience_issues(a) or a["issues"][0]["requirement"] == text
    assert fake.ready_results == [False] and client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is False
    assert all(r.source.id == sid for r in req.load(folder).requirements)
    assert client.post(f"/api/builds/{build_id}/plan").status_code == 409


@pytest.mark.parametrize("raw", ["not json", json.dumps({"requirements": [{"source_id": "m_spoofed", "text": "x"}]})])
async def test_extraction_errors_still_fail_the_turn(client, app, build_id, monkeypatch, raw):
    from dss.spec import requirements as req
    folder = sales_seed(app, build_id, **SALES)
    class Broken(ScriptLLM):
        async def generate_content_async(self, llm_request, stream=False):
            if (llm_request.config.response_json_schema or {}).get("title") == "Extraction":
                self.calls += 1
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=raw)]))
                return
            async for event in super().generate_content_async(llm_request, stream):
                yield event
    fake = Broken()
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    response = client.post(f"/api/builds/{build_id}/messages", json={"text": AUDIENCE})
    assert response.status_code == 202
    await wait_done(app)
    run = [p for kind, p in events(app, build_id) if kind == "run.finished"][-1]
    assert run["status"] == "error" and fake.calls == 1 and fake.interview_calls == 0
    assert [m["role"] for m in client.get(f"/api/builds/{build_id}/messages").json()] == ["user"]
    assert not (folder / "requirements.json").exists() and req.load(folder).requirements == []


def write_legacy(app, build_id, folder, rows):
    """A pre-14.1 ledger whose persisted assessment blocked ordinary audience rows."""
    from dss.spec import capabilities, requirements as req
    snapshot = req.inputs(app.state.db, build_id, folder)
    ledger = req.Ledger(requirements=rows, processed_sources={s["id"]: req.digest(s) for s in snapshot["incoming"]})
    checker = capabilities.Checker(capabilities.load_registry())
    blocked = req.evaluate(snapshot, ledger, checker).model_copy(update={"state": "blocked", "issues": [req.Issue(
        id="issue_legacy", requirement=AUDIENCE, status="unknown", reason="No registered capability covers this requirement")]})
    req.save(folder, ledger, blocked)


async def test_persisted_audience_rows_recover_on_reassessment(client, app, build_id, monkeypatch):
    from dss.spec import requirements as req
    from test_audit_style import drain
    folder = sales_seed(app, build_id, **SALES)
    standalone = episodic.save(app.state.db, build_id, "user", AUDIENCE)
    mixed = episodic.save(app.state.db, build_id, "user", MIXED)
    source = lambda m: req.Source(id=m["id"], kind="message", text=m["text"])
    rows = [req.Requirement(id="req_a", source=source(standalone), text=AUDIENCE),
            req.Requirement(id="req_b", source=source(mixed), text=AUDIENCE, needs=[{"capability": "unknown.unclassified"}]),
            req.Requirement(id="req_c", source=source(mixed), text="Track total revenue", needs=SCORECARD,
                            mappings=[req.Mapping(label="revenue", field="revenue", aggregation="sum")])]
    write_legacy(app, build_id, folder, rows)
    assert client.get(f"/api/builds/{build_id}/feasibility").json()["state"] == "blocked"
    fake = ScriptLLM()
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    assert client.post(f"/api/builds/{build_id}/feasibility/check").status_code == 202
    await drain(app)
    a = client.get(f"/api/builds/{build_id}/feasibility").json()
    assert a["state"] == "ready" and not a["issues"], a
    assert fake.calls == 0  # deterministic reassessment: no new extraction
    ledger = req.load(folder)
    assert [r.id for r in ledger.requirements] == ["req_a", "req_b", "req_c"] and not ledger.decisions
    assert {r.source.id for r in ledger.requirements} == {standalone["id"], mixed["id"]}
    # Genuine unknown rows in the same ledger still block: no blanket recovery.
    rows.append(req.Requirement(id="req_d", source=source(mixed), text="Add a telepathic chart"))
    rows.append(req.Requirement(id="req_e", source=source(standalone), text=AUDIENCE + " Add a telepathic chart"))
    write_legacy(app, build_id, folder, rows)
    assert client.post(f"/api/builds/{build_id}/feasibility/check").status_code == 202
    await drain(app)
    a = client.get(f"/api/builds/{build_id}/feasibility").json()
    assert a["state"] == "blocked" and sorted(i["requirement"] for i in a["issues"]) == sorted(
        ["Add a telepathic chart", AUDIENCE + " Add a telepathic chart"])


def test_audience_recognition_is_bounded():
    from dss.spec import requirements as req
    def row(text, source=None, **fields):
        return req.Requirement(id="r", source=req.Source(id="m", kind="message", text=source or text), text=text, **fields)
    for text in (AUDIENCE, "Help our sales director", "Audience: regional sales managers", "For the CFO and the sales team"):
        assert req.audience_requirement(row(text)), text
    for text in ("Show sales leads", "Help our sales director and animate GPS points",
                 "The audience is sales executives who need GPS playback"):
        assert not req.audience_requirement(row(text)), text
    assert not req.audience_requirement(row(AUDIENCE, needs=SCORECARD))
    assert not req.audience_requirement(row(AUDIENCE, mappings=[req.Mapping(label="revenue", field="revenue")]))
    # A model claim that does not quote the message's own audience clause is not context.
    assert not req.audience_requirement(row("The audience is the CFO", source="Show revenue."))
    # A mixed message without any other row for its remainder fails closed.
    assert not req.audience_requirement(row(AUDIENCE, source=MIXED), req.Ledger())
