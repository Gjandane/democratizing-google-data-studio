"""A scripted fake build agent exercises the real HTTP and Workflow lifecycle."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from dss.config import Config
from dss.db import Database, now
from dss.main import create_app
from dss.recipe.compiler import compile_recipe
from dss.spec.models import DashboardSpec
from fakes import fake_models
from test_api_contract import check, shape, FIXTURES
from test_execute import settle

TOKEN = "fake-agent-token-at-least-24"
CODE = "fake-access-code"
AUTH = {"X-DSS-Agent-Token": TOKEN}
EVENTS = [json.loads(line) for line in (FIXTURES.parent / "events.sample.jsonl").read_text().splitlines()]


@pytest.fixture
def remote(tmp_path, monkeypatch):
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "17")
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "1")
    from dss.api import engine
    async def no_local_engine(*args):
        pytest.fail("agent mode invoked a local engine")
    monkeypatch.setattr(engine, "control_command", no_local_engine)
    app = create_app(Config(data_dir=tmp_path, engine_mode="agent", access_code=CODE,
                            agent_token=TOKEN, google_api_key="fake-google-key", gcp_project_id="deployment"),
                     model_lister=fake_models)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        bid = client.post("/api/builds", json={"archetype": "executive", "mode": "data"}).json()["id"]
        folder = tmp_path / "builds" / bid / "v1"
        folder.mkdir(parents=True, exist_ok=True)
        spec = DashboardSpec.model_validate_json(Path("tests/data/thin_spec.json").read_text())
        spec.build_id = bid
        (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
        (folder / "recipe.jsonl").write_text(compile_recipe(spec, 1), encoding="utf-8", newline="\n")
        (folder / "background_p1.png").write_bytes(b"fake-background")
        with app.state.db.connect() as conn:
            conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (bid,))
        yield client, app, bid, folder


def heartbeat(client, signed_in=True):
    response = client.post("/api/agent/heartbeat", headers=AUTH,
        json={"chrome_running": True, "signed_in": signed_in, "agent_version": "test"})
    assert response.status_code == 200 and response.json() == {"ok": True}


def accept(remote):
    client, app, bid, folder = remote
    heartbeat(client)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 202, response.text
    job = client.get("/api/agent/jobs/next?wait=0", headers=AUTH)
    assert job.status_code == 200, job.text
    return response.json()["run_id"], job.json()


def post_events(client, run_id, events=EVENTS):
    response = client.post(f"/api/agent/jobs/{run_id}/events", headers=AUTH, json={"events": events})
    assert response.status_code == 200, response.text


def finish(client, run_id, code=0, stderr=""):
    response = client.post(f"/api/agent/jobs/{run_id}/finished", headers=AUTH,
                           json={"exit_code": code, "stderr_tail": stderr})
    assert response.status_code == 200, response.text


def records(app, run_id):
    with app.state.db.connect() as conn:
        return [(row["kind"], json.loads(row["payload_json"])) for row in
                conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY rowid", (run_id,))]


def assert_failure(remote, run_id, error):
    client, app, bid, folder = remote
    settle(client, app)
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] == "failed"
    assert build["report_url"] is None
    assert [data for kind, data in records(app, run_id) if kind == "build.finished"] == [
        {"status": "failed", "report_url": None, "version": 1}]
    with app.state.db.connect() as conn:
        rows = conn.execute("SELECT status,error FROM traces WHERE run_id=?", (run_id,)).fetchall()
    assert len(rows) == 1 and tuple(rows[0]) == ("error", error)


def test_offline_heartbeat_status_and_fixture_completion(remote):
    client, app, bid, folder = remote
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 424 and response.json()["error"]["code"] == "agent_offline"
    assert not app.state.engine_busy
    assert client.get("/api/engine/status").json()["agent_last_seen"] is None
    heartbeat(client, signed_in=False)
    status = client.get("/api/engine/status").json()
    assert status["mode"] == "agent" and status["agent_connected"] and not status["signed_in"]
    app.state.agent_jobs.last_seen_clock -= 31
    assert not client.get("/api/engine/status").json()["agent_connected"]
    assert client.post(f"/api/builds/{bid}/run").status_code == 424
    run_id, job = accept(remote)
    shape(job, json.loads((FIXTURES / "agent_job.json").read_text()))
    assert job == dict(run_id=run_id, build_id=bid, version=1, dry_run=True, timeout_s=17,
                       files=["recipe.jsonl", "background_p1.png"])
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 409 and response.json()["error"]["code"] == "engine_busy"
    assert client.get("/api/agent/jobs/next?wait=0", headers=AUTH).status_code == 204
    for name in job["files"]:
        response = client.get(f"/api/agent/jobs/{run_id}/files/{name}", headers=AUTH)
        assert response.status_code == 200 and response.content == (folder / name).read_bytes()
    screenshot = b"\x89PNG\r\n\x1a\nfixture"
    response = client.put(f"/api/agent/jobs/{run_id}/screens/s012_failed.png", headers=AUTH, content=screenshot)
    assert response.status_code == 200
    assert (folder / "screens/s012_failed.png").read_bytes() == screenshot
    post_events(client, run_id, EVENTS[:8])
    post_events(client, run_id, EVENTS[8:])
    finish(client, run_id)
    assert not app.state.engine_busy
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "done" and build["versions"][0]["status"] == "published"
    assert build["report_url"] == EVENTS[-1]["report_url"]
    actual = records(app, run_id)
    assert [data for kind, data in actual if kind == "build.op"] == [e for e in EVENTS if e["event"] == "op_finished"]
    assert [data for kind, data in actual if kind == "build.finished"] == [
        {"status": EVENTS[-1]["status"], "report_url": EVENTS[-1]["report_url"], "version": 1}]
    assert [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()] == EVENTS
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT status FROM traces WHERE run_id=?", (run_id,)).fetchone()[0] == "ok"
    for method, suffix, kwargs in [("get", "files/recipe.jsonl", {}), ("post", "events", {"json": {"events": EVENTS}}),
                                   ("put", "screens/a.png", {"content": b"x"}),
                                   ("post", "finished", {"json": {"exit_code": 0, "stderr_tail": ""}})]:
        response = getattr(client, method)(f"/api/agent/jobs/{run_id}/{suffix}", headers=AUTH, **kwargs)
        assert response.status_code == 404 and response.json()["error"]["code"] == "job_not_found"


@pytest.mark.parametrize("url", ["https://evil.example/report", "https://datastudio.google.com.evil.example/r",
    "http://datastudio.google.com/r", "https://user@lookerstudio.google.com/r", "https://[invalid", 12])
def test_invalid_url_never_persisted_and_releases_lock(remote, url):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    event = {**EVENTS[-1], "report_url": url}
    post_events(client, run_id, [event])
    assert_failure(remote, run_id, "invalid_report_url")
    assert not (folder / "events.jsonl").read_text()
    run_id, _ = accept(remote)
    finish(client, run_id, 1)


@pytest.mark.parametrize("code,status,url,error", [
    (0, "ok", None, None), (0, "partial", "https://lookerstudio.google.com/reporting/test", None),
    (3, "failed", None, "engine_not_signed_in"), (1, "failed", None, None), (2, "failed", None, None),
])
def test_exit_mapping(remote, code, status, url, error):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    post_events(client, run_id, [{**EVENTS[-1], "status": status, "report_url": url}])
    finish(client, run_id, code)
    if error:
        assert_failure(remote, run_id, error)
    else:
        result = [data for kind, data in records(app, run_id) if kind == "build.finished"]
        assert result == [{"status": status, "report_url": url, "version": 1}]


def test_no_finish_event_is_failed(remote):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    finish(client, run_id)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "prototype"


def test_timeout_and_late_agent_then_retry(remote, monkeypatch):
    client, app, bid, folder = remote
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "0")
    import dss.agent.jobs as jobs
    monkeypatch.setattr(jobs, "TIMEOUT_GRACE_S", .12)
    run_id, _ = accept(remote)
    settle(client, app)
    assert_failure(remote, run_id, "agent_timeout")
    assert client.post(f"/api/agent/jobs/{run_id}/events", headers=AUTH, json={"events": EVENTS}).status_code == 404
    assert client.get("/api/agent/jobs/next?wait=0", headers=AUTH).status_code == 204
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "17")
    retry, _ = accept(remote)
    finish(client, retry, 1)


def test_events_refresh_timeout_but_heartbeats_do_not(remote, monkeypatch):
    client, app, bid, folder = remote
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "0")
    import dss.agent.jobs as jobs
    monkeypatch.setattr(jobs, "TIMEOUT_GRACE_S", .4)
    run_id, _ = accept(remote)
    time.sleep(.25)
    post_events(client, run_id, [EVENTS[0]])
    time.sleep(.25)
    assert app.state.engine_busy
    heartbeat(client)
    settle(client, app)
    assert_failure(remote, run_id, "agent_timeout")


def test_queued_job_also_times_out(remote, monkeypatch):
    client, app, bid, folder = remote
    import dss.agent.jobs as jobs
    monkeypatch.setattr(jobs, "TIMEOUT_GRACE_S", .1)
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "0")
    heartbeat(client)
    run_id = client.post(f"/api/builds/{bid}/run").json()["run_id"]
    assert_failure(remote, run_id, "agent_timeout")
    assert client.get("/api/agent/jobs/next?wait=0", headers=AUTH).status_code == 204


def test_long_poll_and_two_agents_do_not_block_requests(remote):
    client, app, bid, folder = remote
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(client.get, "/api/agent/jobs/next?wait=.4", headers=AUTH)
        second = pool.submit(client.get, "/api/agent/jobs/next?wait=.4", headers=AUTH)
        time.sleep(.05)
        assert not first.done() and not second.done()
        started = time.monotonic()
        heartbeat(client)
        assert client.get("/api/health").status_code == 200
        assert time.monotonic() - started < .3
        response = client.post(f"/api/builds/{bid}/run")
        assert response.status_code == 202
        responses = [first.result(timeout=3), second.result(timeout=3)]
    assert sorted(response.status_code for response in responses) == [200, 204]
    finish(client, response.json()["run_id"], 1)
    assert client.get("/api/agent/jobs/next?wait=26", headers=AUTH).status_code == 422


@pytest.mark.parametrize("method,suffix,kwargs", [
    ("get", "jobs/next?wait=0", {}),
    ("post", "heartbeat", {"json": {"chrome_running": True, "signed_in": True, "agent_version": "test"}}),
    ("get", "jobs/missing/files/recipe.jsonl", {}),
    ("put", "jobs/missing/screens/a.png", {"content": b"png"}),
    ("post", "jobs/missing/events", {"json": {"events": EVENTS}}),
    ("post", "jobs/missing/finished", {"json": {"exit_code": 0, "stderr_tail": ""}}),
])
def test_token_required_and_access_code_is_not_agent_auth(remote, method, suffix, kwargs):
    client, *_ = remote
    for headers in ({}, {"X-DSS-Agent-Token": CODE}, {"X-DSS-Agent-Token": "wrong-token"}):
        response = getattr(client, method)("/api/agent/" + suffix, headers=headers, **kwargs)
        assert response.status_code == 401 and response.json()["error"]["code"] == "agent_unauthorized"


@pytest.mark.parametrize("suffix", ["%2e%2e/dss.sqlite", "%2e%2e", "screens/x.png", "bad%5cname.png", "not-listed.png"])
def test_file_boundaries(remote, suffix):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    for method, segment in (("get", "files"), ("put", "screens")):
        if segment == "screens" and suffix == "not-listed.png":
            continue  # Any plain PNG name is allowed for screenshots.
        response = getattr(client, method)(f"/api/agent/jobs/{run_id}/{segment}/{suffix}", headers=AUTH)
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_name"
    finish(client, run_id, 1)


def add_images(folder, *paths):
    """Image components below the thin layout; run recompiles them into add_image inputs."""
    spec = DashboardSpec.model_validate_json((folder / "spec.json").read_text())
    template = spec.pages[0].components[0].model_dump()
    for i, path in enumerate(paths, len(spec.pages[0].components)):
        grid = {**template["grid"], "row": 20 + 3 * i}  # rows 29-38 for i = 3..6: inside the canvas
        spec.pages[0].components.append(type(spec.pages[0].components[0]).model_validate(
            {**template, "id": f"p1_image{i}", "type": "image", "image_path": path, "grid": grid}))
    (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")


def test_all_recipe_inputs_in_order_and_bad_inputs_fail_before_lock(remote):
    client, app, bid, folder = remote
    add_images(folder, "logo.png", "background_p1.png", "logo.png")
    (folder / "logo.png").write_bytes(b"logo")
    run_id, job = accept(remote)
    assert job["files"] == ["recipe.jsonl", "background_p1.png", "logo.png"]
    finish(client, run_id, 1)
    settle(client, app)
    add_images(folder, "../dss.sqlite")
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_name"
    assert not app.state.engine_busy


def test_secrets_redacted_from_events_and_stderr(remote, caplog):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    text = f"{TOKEN} {CODE} fake-google-key"
    post_events(client, run_id, [{**EVENTS[2], "message": text}, EVENTS[-1]])
    finish(client, run_id, 0, text)
    serialized = json.dumps(records(app, run_id)) + (folder / "events.jsonl").read_text() + caplog.text
    for secret in (TOKEN, CODE, "fake-google-key"):
        assert secret not in serialized
    assert "[redacted]" in serialized


def test_login_settings_lock_and_deployment_overrides(remote):
    client, app, bid, folder = remote
    response = client.post("/api/engine/login")
    assert response.status_code == 409 and response.json()["error"]["code"] == "login_on_agent"
    for field in ("google_api_key", "gcp_project_id", "bq_dataset", "bq_location", "gcs_bucket"):
        response = client.put("/api/settings", json={field: "changed", "worker_model": "new"})
        assert response.status_code == 403 and response.json()["error"]["code"] == "settings_locked"
    response = client.put("/api/settings", json={"planner_model": "planner", "worker_model": "worker"})
    assert response.status_code == 200 and response.json()["worker_model"] == "worker"
    app.state.settings.update({"gcp_project_id": "old-local-project", "google_api_key": "old-key"})
    config = app.state.settings.get()
    assert config.gcp_project_id == "deployment" and config.google_api_key.get_secret_value() == "fake-google-key"


@pytest.mark.parametrize("mode,fixture", [("agent", "engine_status.json"), ("local", "engine_status.local.json")])
def test_status_contract_variants(tmp_path, monkeypatch, mode, fixture):
    from dss.api import engine
    async def fake_check(*args):
        return 0, '{"chrome_running": true, "signed_in": true}'
    monkeypatch.setattr(engine, "control_command", fake_check)
    app = create_app(Config(data_dir=tmp_path, engine_mode=mode, agent_token=TOKEN), model_lister=fake_models)
    with TestClient(app) as client:
        if mode == "agent":
            heartbeat(client)
        check(client.get("/api/engine/status"), fixture)
        if mode == "local":
            for method, path in (("get", "jobs/next"), ("post", "heartbeat"), ("put", "jobs/x/screens/a.png"), ("get", "unknown")):
                response = getattr(client, method)("/api/agent/" + path, headers=AUTH)
                assert response.status_code == 404 and response.json()["error"]["code"] == "agent_mode_off"


def test_startup_recovers_interrupted_job_once(tmp_path):
    db = Database(tmp_path / "dss.sqlite")
    db.initialize()
    bid, run_id = "b_123456789abc", "r_123456789abc"
    with db.connect() as conn:
        conn.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (bid, "Interrupted", "executive", "data", "build", now(), now()))
        conn.execute("INSERT INTO versions(build_id,n,status,created_at) VALUES(?,1,'building',?)", (bid, now()))
        conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", ("e_test", bid, run_id, "run.started",
                     json.dumps({"run_id": run_id, "node": "execute"}), now()))
    for _ in range(2):
        app = create_app(Config(data_dir=tmp_path, engine_mode="agent", agent_token=TOKEN), model_lister=fake_models)
        with TestClient(app) as client:
            assert_failure((client, app, bid, tmp_path), run_id, "agent_timeout")
            assert client.get("/api/agent/jobs/next?wait=0", headers=AUTH).status_code == 204


def test_shutdown_cancels_job_and_wakes_long_poll(remote):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    async def close():
        poll = asyncio.create_task(app.state.agent_jobs.next(25))
        await asyncio.sleep(.01)
        await app.state.agent_jobs.close()
        assert await asyncio.wait_for(poll, .5) is None
        tasks = tuple(app.state.engine_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    client.portal.call(close)
    assert not app.state.engine_busy and not app.state.harness.active_builds
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "prototype"


def job_recipe(client, run_id):
    response = client.get(f"/api/agent/jobs/{run_id}/files/recipe.jsonl", headers=AUTH)
    assert response.status_code == 200
    return response.content.decode("utf-8")


def test_job_ships_recipe_of_revised_spec(remote, monkeypatch):
    from test_revise import seed_revision, revise_through_api
    client, app, bid, folder = remote
    seed_revision(app, bid, monkeypatch)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    stale = (folder / "recipe.jsonl").read_text(encoding="utf-8")
    revised = revise_through_api(client, app, bid)
    run_id, job = accept(remote)
    shipped = job_recipe(client, run_id)
    assert shipped == compile_recipe(revised, 1) and shipped != stale
    chart = json.loads(shipped.split("\n")[4])
    assert chart["component_id"] == "p1_revenue" and chart["title"] == "Net revenue" and chart["w"] > 568
    post_events(client, run_id)
    finish(client, run_id)
    settle(client, app)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "done"


def test_refresh_failure_queues_no_job(remote):
    client, app, bid, folder = remote
    previous, good = (folder / "recipe.jsonl").read_bytes(), (folder / "spec.json").read_text()
    add_images(folder, None)  # an image without a path cannot compile
    heartbeat(client)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_recipe"
    assert client.get("/api/agent/jobs/next?wait=0", headers=AUTH).status_code == 204
    assert not app.state.agent_jobs.running and not app.state.engine_tasks
    assert not app.state.engine_busy and bid not in app.state.harness.active_builds
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "prototype"
    assert (folder / "recipe.jsonl").read_bytes() == previous
    (folder / "spec.json").write_text(good, encoding="utf-8")
    run_id, _ = accept(remote)
    assert job_recipe(client, run_id) == previous.decode("utf-8")
    finish(client, run_id, 1)
    settle(client, app)


def test_recipe_request_cannot_mutate_unreleased_job_files(remote):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    shipped = job_recipe(client, run_id)
    # The Workflow can publish (stage back to prototype) and drop its build lock before the
    # request's finally releases the job; the agent may still be downloading in that window.
    spec = DashboardSpec.model_validate_json((folder / "spec.json").read_text())
    spec.pages[0].components[0].label = "Changed mid-build"
    (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (bid,))
    app.state.harness.active_builds.discard(bid)
    response = client.post(f"/api/builds/{bid}/recipe")
    assert response.status_code == 409 and response.json()["error"]["code"] == "wrong_stage"
    assert job_recipe(client, run_id) == shipped
    finish(client, run_id, 1)
    settle(client, app)
    response = client.post(f"/api/builds/{bid}/recipe")
    assert response.status_code == 200
    assert "Changed mid-build" in (folder / "recipe.jsonl").read_text(encoding="utf-8")


NESTED = {"images/logo.png": b"nested logo", "brand/logo.png": b"brand logo", "logo.png": b"plain logo",
          "images/deep/My Logo (1).png": b"spaced logo"}


def nested_inputs(folder):
    for path, content in NESTED.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(content)
    paths = ["images/logo.png", "brand/logo.png", "images/logo.png", "logo.png",
             "images/deep/My Logo (1).png", "background_p1.png"]
    add_images(folder, *paths)
    spec = DashboardSpec.model_validate_json((folder / "spec.json").read_text())
    for i, image in enumerate(spec.pages[0].components[-len(paths):]):  # two per row: inside the canvas
        image.grid.row, image.grid.col, image.grid.w, image.grid.h = 27 + 3 * (i // 2), 1 + 6 * (i % 2), 6, 2
    (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")


def test_nested_images_package_to_plain_deduplicated_names(remote):
    from dss.agent.jobs import PLAIN, package
    client, app, bid, folder = remote
    nested_inputs(folder)
    originals = {path: (folder / path).read_bytes() for path in [*NESTED, "background_p1.png"]}
    run_id, job = accept(remote)
    canonical = compile_recipe(DashboardSpec.model_validate_json((folder / "spec.json").read_text()), 1)
    assert (folder / "recipe.jsonl").read_bytes() == canonical.encode("utf-8")  # canonical bytes kept
    files = job["files"]
    assert files[0] == "recipe.jsonl" and len(files) == len(set(f.casefold() for f in files)) == 6
    assert all(PLAIN.fullmatch(name) and name not in (".", "..") for name in files)
    assert files[1] == "background_p1.png" and "logo.png" in files
    downloaded = {name: client.get(f"/api/agent/jobs/{run_id}/files/{name}", headers=AUTH) for name in files}
    assert all(response.status_code == 200 for response in downloaded.values())
    shipped, original = downloaded["recipe.jsonl"].content.decode("utf-8"), canonical
    assert shipped.endswith("\n") and len(shipped.split("\n")) == len(original.split("\n"))
    sources = {}
    for sent, kept in zip(shipped.split("\n"), original.split("\n")):
        if not kept:
            continue
        sent_op, kept_op = json.loads(sent), json.loads(kept)
        if "path" not in kept_op or PLAIN.fullmatch(kept_op["path"]):
            assert sent == kept  # unrenamed lines keep their canonical bytes
            continue
        assert {**sent_op, "path": kept_op["path"]} == kept_op
        sources.setdefault(kept_op["path"], set()).add(sent_op["path"])
    # Repeated sources share one name; same basenames in other folders never collide.
    assert all(len(names) == 1 for names in sources.values()) and len(sources) == 3
    names = {path: names.pop() for path, names in sources.items()}
    assert names["images/logo.png"] != names["brand/logo.png"]
    for path, name in [*names.items(), ("logo.png", "logo.png"), ("background_p1.png", "background_p1.png")]:
        assert downloaded[name].content == originals[path]
    ops = [json.loads(line) for line in shipped.split("\n")[1:-1]]
    assert sorted({op["path"] for op in ops if "path" in op}) == sorted(files[1:])
    assert [op["path"] for op in ops if op["op"] == "add_image"].count(names["images/logo.png"]) == 2
    # Deterministic: repackaging matches the shipped job byte for byte; the folder is untouched.
    for _ in range(2):
        again = package(folder)
        assert list(again) == files and again["recipe.jsonl"] == shipped.encode("utf-8")
    assert {path: (folder / path).read_bytes() for path in originals} == originals
    assert not any(name.startswith("asset-") for name in (p.name for p in folder.rglob("*")))
    post_events(client, run_id)
    finish(client, run_id)
    settle(client, app)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "done"
    assert (folder / "recipe.jsonl").read_bytes() == canonical.encode("utf-8")


def outside_link(folder, tmp_path):
    """A folder link inside the version that resolves outside it (a junction without symlink rights)."""
    target = tmp_path / "outside"
    target.mkdir()
    (target / "x.png").write_bytes(b"outside")
    try:
        (folder / "linked").symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("symlinks are unavailable here")
        import _winapi
        _winapi.CreateJunction(str(target), str(folder / "linked"))
    return "linked/x.png"


@pytest.mark.parametrize("bad,code", [
    ("../dss.sqlite", "invalid_name"), ("images/../../dss.sqlite", "invalid_name"),
    ("images/../logo.png", "invalid_name"), (r"images\..\..\dss.sqlite", "invalid_name"),
    ("./logo.png", "invalid_name"), ("images//logo.png", "invalid_name"), ("/etc/passwd", "invalid_name"),
    ("C:/Windows/win.ini", "invalid_name"), ("C:logo.png", "invalid_name"), (r"\\host\share\x.png", "invalid_name"),
    ("absolute", "invalid_name"), ("link", "invalid_name"), ("images", "invalid_recipe"),
    ("images/missing.png", "invalid_recipe")])
def test_bad_image_paths_reject_before_queueing(remote, tmp_path, bad, code):
    client, app, bid, folder = remote
    (folder / "images").mkdir()
    (folder / "logo.png").write_bytes(b"logo")
    good = (folder / "spec.json").read_text()
    if bad == "absolute":
        bad = str((tmp_path / "outside.png"))
        (tmp_path / "outside.png").write_bytes(b"outside")
    elif bad == "link":
        bad = outside_link(folder, tmp_path)
    add_images(folder, "logo.png", bad)
    heartbeat(client)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == (400 if code == "invalid_name" else 422), response.text
    assert response.json()["error"]["code"] == code
    assert client.get("/api/agent/jobs/next?wait=0", headers=AUTH).status_code == 204
    assert not app.state.agent_jobs.running and not app.state.agent_jobs.jobs and not app.state.engine_tasks
    assert not app.state.engine_busy and bid not in app.state.harness.active_builds
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] != "building"
    (folder / "spec.json").write_text(good, encoding="utf-8")
    run_id, job = accept(remote)  # the stage and lock are still usable
    assert job["files"] == ["recipe.jsonl", "background_p1.png"]
    finish(client, run_id, 1)
    settle(client, app)
