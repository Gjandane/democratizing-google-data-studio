import asyncio
import json
from pathlib import Path
import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from dss.harness.guardrails import RunError
from dss.harness.context import interview_context
from dss.memory import episodic
from fakes import FakeLLM


class ReadyLLM(FakeLLM):
    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        if self.calls == 1:
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
        assert [s["node"] for s in json.loads(rows[0]["spans_json"])] == ["router", "interview", "guardrail"]


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


@pytest.mark.parametrize("forbidden", ["test-key", "mark_ready_for_plan"])
async def test_split_forbidden_stream(client, app, build_id, forbidden):
    from dss.harness.nodes.interview import ReplyStream
    stream = ReplyStream(app.state.harness, build_id, "r_stream")
    await stream.append("Safe preface. " * 4 + forbidden[:3])
    with pytest.raises(RunError):
        await stream.append(forbidden[3:])
    published = "".join(p["text"] for k, p in events(app, build_id) if k == "message.delta")
    assert forbidden not in published and forbidden[:3] not in published
