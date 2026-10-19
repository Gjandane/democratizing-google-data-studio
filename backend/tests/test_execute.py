import json
import time
import pytest
from test_thin_slice import thin, load, wait_done


def settle(client, app):
    for _ in range(300):
        if not app.state.engine_busy:
            return
        time.sleep(.02)
    pytest.fail("engine lock was not released")


def test_fixture_run_and_versions(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    monkeypatch.setenv("DSS_FAKE_FIXTURE", "1")
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "23")
    accepted = client.post(f"/api/builds/{bid}/run")
    assert accepted.status_code == 202
    busy = client.post(f"/api/builds/{bid}/run")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "engine_busy"
    settle(client, app)
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "done"
    assert build["versions"][0]["status"] == "published"
    from pathlib import Path
    fixture = [json.loads(line) for line in (Path(__file__).resolve().parents[2] / "contracts/fixtures/events.sample.jsonl").read_text().splitlines()]
    assert [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()] == fixture
    with app.state.db.connect() as conn:
        events = [(row["kind"], json.loads(row["payload_json"])) for row in conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY rowid", (accepted.json()["run_id"],))]
    assert [data for kind, data in events if kind == "build.op"] == [e for e in fixture if e["event"] == "op_finished"]
    assert [data for kind, data in events if kind == "build.finished"] == [{"status":fixture[-1]["status"], "report_url":fixture[-1]["report_url"], "version":1}]
    flags = json.loads((folder / "fake-args.json").read_text())
    assert flags[flags.index("--timeout")+1] == "23" and "--dry-run" in flags
    old_spec = json.loads((folder / "spec.json").read_text())
    response = client.post(f"/api/builds/{bid}/versions")
    assert response.status_code == 201, response.text
    assert response.json()["current_version"] == 2 and response.json()["stage"] == "prototype"
    assert response.json()["versions"][1]["status"] == "draft"
    new = folder.parent / "v2"
    assert json.loads((new / "spec.json").read_text())["datasource"] == old_spec["datasource"]
    assert not (new / "recipe.jsonl").exists() and not (new / "events.jsonl").exists()
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    assert json.loads((new / "recipe.jsonl").read_text().splitlines()[0])["version"] == 2


def test_not_signed_in_and_retry(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    client.post(f"/api/builds/{bid}/recipe")
    monkeypatch.setenv("DSS_FAKE_EXIT", "3")
    run_id = client.post(f"/api/builds/{bid}/run").json()["run_id"]
    settle(client, app)
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] == "failed"
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT error FROM traces WHERE run_id=?", (run_id,)).fetchone()[0] == "engine_not_signed_in"
        result = json.loads(conn.execute("SELECT payload_json FROM events WHERE run_id=? AND kind='build.finished'", (run_id,)).fetchone()[0])
    assert result == {"status":"failed", "report_url":None, "version":1}
    monkeypatch.delenv("DSS_FAKE_EXIT")
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    settle(client, app)
    assert wait_done(client, bid)["stage"] == "done"


def test_engine_endpoints(thin):
    client, app, bid, folder = thin
    assert client.get("/api/engine/status").json() == {"mode":"local", "chrome_running":True, "signed_in":True, "agent_connected":False, "agent_last_seen":None}
    assert client.post("/api/engine/login").status_code == 202
    settle(client, app)
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT status FROM traces WHERE node='engine_login'").fetchone()[0] == "ok"


@pytest.mark.parametrize("command", ["check", "login"])
def test_control_lock_and_cancel(thin, monkeypatch, command):
    import asyncio
    from starlette.requests import Request
    from dss.api.engine import status
    client, app, bid, folder = thin
    marker = folder.parent / "control-started"
    marker.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DSS_FAKE_CONTROL_HANG", command)
    monkeypatch.setenv("DSS_FAKE_CONTROL_MARKER", str(marker))
    async def exercise():
        if command == "check":
            task = asyncio.create_task(status(Request({"type":"http", "app":app})))
        else:
            response = await asyncio.to_thread(client.post, "/api/engine/login")
            assert response.status_code == 202
            task = next(iter(app.state.engine_tasks))
        for _ in range(250):
            if marker.exists():
                break
            await asyncio.sleep(.02)
        assert marker.exists()
        assert app.state.engine_busy
        response = await asyncio.to_thread(client.post, "/api/engine/login")
        assert response.status_code == 409
        assert (await asyncio.to_thread(client.get, "/api/health")).status_code == 200
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert not app.state.engine_busy
    client.portal.call(exercise)
