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

    async def generate_content_async(self, llm_request, stream=False):
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
    fake = FakeLLM(extra_capability=capability, ambiguous=capability is None)
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    message = "Show Revenue" if capability is None else "Show a Revenue scorecard and animate GPS points along a route"
    response = client.post(f"/api/builds/{build_id}/messages", json={"text": message})
    assert response.status_code == 202
    await wait_done(app)
    assert fake.extraction_calls == fake.calls == 1
    assert fake.extracted_source_ids == [response.json()["message_id"]]
    assessment = client.get(f"/api/builds/{build_id}/feasibility").json()
    assert assessment["state"] == "blocked"
    assert status in [issue["status"] for issue in assessment["issues"]]
    assert client.get(f"/api/builds/{build_id}").json()["ready_for_plan"] is False
    folder = app.state.settings.get().data_dir / "builds" / build_id / "v1"
    ledger = req.load(folder)
    assert ledger.requirements[0].source.id == response.json()["message_id"]
    history = client.get(f"/api/builds/{build_id}/messages").json()
    explanation = history[-1]["text"]
    assert history[-1]["role"] == "assistant"
    if status == "unsupported_app":
        assert "alternative" in explanation.lower() and "time" in explanation.lower()
    else:
        assert "clarify" in explanation.lower()
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT * FROM traces WHERE build_id=?", (build_id,)).fetchall()
    assert len(traces) == 1
    assert "capability_check" in [span["node"] for span in json.loads(traces[0]["spans_json"])]
    assert events(app, build_id)[-1][1]["status"] == "error"
    blocked = client.post(f"/api/builds/{build_id}/plan")
    assert blocked.status_code == 409
    detail = blocked.json()["error"]["detail"]
    assert detail["assessment_id"] == assessment["id"]
    current = client.get(f"/api/builds/{build_id}/feasibility").json()
    assert detail["assessment_id"] == current["id"]
    assert set(detail["issue_ids"]) == {issue["id"] for issue in current["issues"] if issue["resolution"] == "unresolved"}
    assert fake.calls == 1 and not service.views and not service.dry_runs


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
    assert fake.extraction_calls == 1 and fake.interview_calls == (2 if ready else 0)
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
