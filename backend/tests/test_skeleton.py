import asyncio
import json
from pathlib import Path

import pytest
from google.adk import Workflow
from fastapi.testclient import TestClient

from dss.config import Config
from dss.harness.guardrails import RunError
from dss.main import create_app
from fakes import FakeLLM


def test_health_and_settings(client, app):
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.put("/api/settings", json={"google_api_key": "new-secret"})
    assert response.status_code == 200
    assert response.json()["google_api_key_set"] is True
    assert "new-secret" not in client.get("/api/settings").text
    assert "google_api_key" not in response.json()
    fixture = json.loads((Path(__file__).parents[2] / "contracts/fixtures/api/settings.json").read_text())
    assert {k: type(v) for k, v in response.json().items()} == {k: type(v) for k, v in fixture.items()}
    with TestClient(create_app(Config(data_dir=app.state.db.path.parent), model_lister=app.state.models.model_lister)) as second:
        assert second.get("/api/settings").json()["google_api_key_set"] is True
    assert client.put("/api/settings", json={"google_api_key": None}).status_code == 422
    assert "new-secret" not in client.put("/api/settings", json={"unexpected": "new-secret"}).text
    assert client.get("/api/nope").json()["error"]["code"] == "not_found"


async def test_sse_ready_delivery_and_cleanup(client, app, build_id):
    # Exercise the route via ASGI directly: TestClient buffers infinite responses.
    sent = []
    first = asyncio.Event()
    disconnect = asyncio.Event()
    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and b"event: ready" in message.get("body", b""):
            first.set()
        if message["type"] == "http.response.body" and b"event: node.progress" in message.get("body", b""):
            disconnect.set()
    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "path": f"/api/builds/{build_id}/events", "query_string": b"", "headers": [],
             "server": ("test", 80), "client": ("test", 1), "scheme": "http"}
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(first.wait(), 3)
    await app.state.bus.publish(build_id, "node.progress", {"text": "working"})
    await asyncio.wait_for(task, 3)
    body = b"".join(message.get("body", b"") for message in sent)
    assert f'"build_id": "{build_id}"'.encode() in body
    assert b"event: node.progress" in body
    assert not app.state.bus.subscribers
    assert client.get("/api/builds/missing/events").status_code == 404


async def test_hello_workflow_trace(client, app, build_id):
    fake = FakeLLM()
    result = await app.state.harness.run("hello", build_id, {}, llm=fake)
    assert result["reply"] == "Hello!"
    assert fake.calls == 1
    with app.state.db.connect() as connection:
        rows = connection.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "ok"
        assert [s["node"] for s in json.loads(row["spans_json"])] == ["router", "hello_function", "hello_llm", "guardrail"]
        assert row["input_tokens"] == 5 and row["output_tokens"] == 2
        assert connection.execute("SELECT text FROM messages_fts WHERE messages_fts MATCH 'Hello'").fetchone()[0] == "Hello!"
        assert [r[0] for r in connection.execute("SELECT kind FROM events ORDER BY rowid")] == ["run.started", "run.usage", "run.finished"]


async def test_unknown_failure_and_lock_release(client, app, build_id, caplog):
    fake = FakeLLM()
    with pytest.raises(RunError):
        await app.state.harness.run("unknown", build_id, llm=fake)
    assert fake.calls == 0
    with pytest.raises(RunError, match="model call failed"):
        await app.state.harness.run("hello", build_id, llm=FakeLLM(fail=True))
    assert not app.state.harness.active_builds
    assert "provider error containing sensitive content" not in caplog.text
    with app.state.db.connect() as connection:
        rows = connection.execute("SELECT status,error FROM traces").fetchall()
        assert len(rows) == 2 and all(row["status"] == "error" for row in rows)
        assert "sensitive" not in str([tuple(r) for r in rows])


async def test_concurrent_build_actions(client, app, build_id):
    started, release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(app.state.harness.run("hello", build_id, llm=FakeLLM(started=started, release=release)))
    try:
        await asyncio.wait_for(started.wait(), 3)
        with pytest.raises(RunError) as exc:
            await app.state.harness.run("hello", build_id, llm=FakeLLM())
        assert exc.value.status_code == 409 and exc.value.code == "wrong_stage"
    finally:
        release.set()
        await task
    with app.state.db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM traces").fetchone()[0] == 1


async def test_planner_fallback_and_refresh(client, app, caplog):
    calls = []
    async def available(key):
        calls.append(True)
        return ["models/gemini-3.8-flash"]
    app.state.models.model_lister = available
    response = client.put("/api/settings", json={"planner_model": "missing-planner"})
    assert response.status_code == 200
    assert app.state.models.model_for("plan") == "gemini-3.8-flash"
    assert app.state.models.model_for("spec") == "gemini-3.8-flash"
    assert "Planner model unavailable" in caplog.text
    assert "test-key" not in caplog.text
    assert len(calls) == 1


async def test_guardrail_rejects_secret(client, app, build_id):
    with pytest.raises(RunError):
        await app.state.harness.run("hello", build_id, llm=FakeLLM(response="test-key"))
    with app.state.db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert "test-key" not in connection.execute("SELECT spans_json FROM traces").fetchone()[0]
