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


def engine_inputs(monkeypatch):
    """Record the recipe text the engine subprocess receives, at the moment it starts."""
    from pathlib import Path
    from dss.harness.nodes import execute as module
    seen, real = [], module.subprocess.Popen
    def popen(args, **kwargs):
        recipe = [arg for arg in args if str(arg).endswith("recipe.jsonl")]
        if recipe:
            seen.append(Path(recipe[0]).read_text(encoding="utf-8"))
        return real(args, **kwargs)
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    return seen


def test_unchanged_spec_run_is_deterministic(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    recipe = folder / "recipe.jsonl"
    before, stamp = recipe.read_bytes(), recipe.stat().st_mtime_ns
    seen = engine_inputs(monkeypatch)
    for _ in range(2):
        assert client.post(f"/api/builds/{bid}/run").status_code == 202
        assert wait_done(client, bid)["stage"] == "done"
        settle(client, app)
        with app.state.db.connect() as conn:
            conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (bid,))
    assert seen == [before.decode("utf-8")] * 2
    assert recipe.read_bytes() == before and recipe.stat().st_mtime_ns == stamp


@pytest.mark.parametrize("breakage", ["uncompilable", "invalid_json"])
def test_refresh_failure_starts_nothing(thin, monkeypatch, breakage):
    from dss.spec.models import DashboardSpec
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    previous, good = (folder / "recipe.jsonl").read_bytes(), (folder / "spec.json").read_text()
    spec = DashboardSpec.model_validate_json(good)
    if breakage == "uncompilable":
        spec.pages[0].components[0].type, spec.pages[0].components[0].image_path = "image", None
        (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    else:
        (folder / "spec.json").write_text("{", encoding="utf-8")
    seen = engine_inputs(monkeypatch)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_recipe"
    assert not seen and not app.state.engine_tasks
    assert not app.state.engine_busy and bid not in app.state.harness.active_builds
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] == "draft"
    assert (folder / "recipe.jsonl").read_bytes() == previous and not (folder / "recipe.jsonl.tmp").exists()
    (folder / "spec.json").write_text(good, encoding="utf-8")
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    assert wait_done(client, bid)["stage"] == "done"
    assert seen == [previous.decode("utf-8")]


async def test_replan_replaces_spec_before_run(client, app, build_id, monkeypatch):
    import asyncio
    import sys
    from dss.recipe.compiler import compile_recipe
    from dss.spec.models import DashboardSpec
    import test_spec_node
    from test_plan import FakeLLM, FakeBigQuery, PLAN
    from test_thin_slice import ROOT
    monkeypatch.setenv("DSS_ENGINE_CMD", f'"{sys.executable}" "{ROOT / "tests/fake_engine.py"}"')
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "1")
    monkeypatch.setattr("dss.render.background.capture", lambda html, path, width, height: path.write_bytes(b"PNG"))
    test_spec_node.spec_seed(app, build_id)
    folder = app.state.settings.get().data_dir / "builds" / build_id / "v1"
    service = FakeBigQuery()
    app.state.bigquery_factory = lambda config: service
    async def plan(label):
        original = test_spec_node.response_for
        def respond(request):
            spec = original(request)
            spec["pages"][0]["components"][0]["label"] = label
            return spec
        monkeypatch.setattr(test_spec_node, "response_for", respond)
        fake = FakeLLM(response=json.dumps(PLAN))
        monkeypatch.setattr(app.state.models, "llm_for", lambda node: fake)
        assert client.post(f"/api/builds/{build_id}/plan").status_code == 202
        for _ in range(500):
            if not app.state.engine_tasks:
                break
            await asyncio.sleep(.01)
        monkeypatch.setattr(test_spec_node, "response_for", original)
        assert client.get(f"/api/builds/{build_id}").json()["stage"] == "prototype"
    await plan("Revenue")
    assert client.post(f"/api/builds/{build_id}/recipe").status_code == 200
    stale = (folder / "recipe.jsonl").read_text(encoding="utf-8")
    await plan("Replanned revenue")
    replanned = DashboardSpec.model_validate_json((folder / "spec.json").read_text())
    assert replanned.pages[0].components[0].label == "Replanned revenue"
    seen = engine_inputs(monkeypatch)
    assert client.post(f"/api/builds/{build_id}/run").status_code == 202
    for _ in range(500):
        if client.get(f"/api/builds/{build_id}").json()["stage"] != "build":
            break
        await asyncio.sleep(.02)
    assert client.get(f"/api/builds/{build_id}").json()["stage"] == "done"
    assert seen == [compile_recipe(replanned, 1)] and seen[0] != stale and "Replanned revenue" in seen[0]
