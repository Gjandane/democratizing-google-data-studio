"""A scripted fake one-shot build agent exercises the real HTTP and Workflow lifecycle (api.md 3.4)."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time

from fastapi.testclient import TestClient
import pytest

from dss.agent.jobs import stamp
from dss.config import Config
from dss.db import Database, now
from dss.main import create_app
from dss.recipe.compiler import compile_recipe
from dss.spec.models import DashboardSpec
from fakes import fake_models
from test_api_contract import check, shape, FIXTURES

CODE = "fake-access-code"
HOSTED = FIXTURES.parent / "hosted-build"
CODE_FORMAT = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
EVENTS = [json.loads(line) for line in (FIXTURES.parent / "events.sample.jsonl").read_text().splitlines()]
TOKENS = {}  # run_id -> X-DSS-Job-Token headers of the fake agent that claimed it


def auth(run_id):
    return TOKENS.get(run_id, {})


def agent_app(tmp_path, **config):
    return create_app(Config(data_dir=tmp_path, engine_mode="agent", access_code=CODE,
                             google_api_key="fake-google-key", gcp_project_id="deployment", **config),
                      model_lister=fake_models)


def make_build(client, app, tmp_path):
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
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
    return bid, folder


@pytest.fixture
def remote(tmp_path, monkeypatch):
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "17")
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "1")
    from dss.api import engine
    async def no_local_engine(*args):
        pytest.fail("agent mode invoked a local engine")
    monkeypatch.setattr(engine, "control_command", no_local_engine)
    app = agent_app(tmp_path)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        bid, folder = make_build(client, app, tmp_path)
        yield client, app, bid, folder


def settle(client, app, bid=None):
    for _ in range(300):
        if (bid not in app.state.harness.active_builds) if bid else not app.state.engine_tasks:
            return
        time.sleep(.02)
    pytest.fail("the run was not released")


def ticket(client, bid):
    response = client.get(f"/api/builds/{bid}/job")
    assert response.status_code == 200, response.text
    return response.json()


def claim(client, code, status=200):
    response = client.post("/api/agent/claim", json={"code": code, "agent_version": "test"})
    assert response.status_code == status, response.text
    return response


def issue(client, bid):
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def accept(remote, bid=None):
    """POST /run, then a fake agent claims the ticket's code; returns the run and its Job."""
    client, app, default, folder = remote
    run_id = issue(client, bid or default)
    claimed = claim(client, ticket(client, bid or default)["code"]).json()
    TOKENS[run_id] = {"X-DSS-Job-Token": claimed["job_token"]}
    return run_id, claimed["job"]


def post_events(client, run_id, events=EVENTS):
    response = client.post(f"/api/agent/jobs/{run_id}/events", headers=auth(run_id), json={"events": events})
    assert response.status_code == 200, response.text


def finish(client, run_id, code=0, stderr=""):
    response = client.post(f"/api/agent/jobs/{run_id}/finished", headers=auth(run_id),
                           json={"exit_code": code, "stderr_tail": stderr})
    assert response.status_code == 200, response.text


def sweep(client, app):
    client.portal.call(app.state.agent_jobs.sweep)


def backdate(app, run_id, column, seconds):
    moment = stamp(datetime.now(timezone.utc) - timedelta(seconds=seconds))
    with app.state.db.connect() as conn:
        conn.execute(f"UPDATE agent_tickets SET {column}=? WHERE run_id=?", (moment, run_id))


def records(app, run_id):
    with app.state.db.connect() as conn:
        return [(row["kind"], json.loads(row["payload_json"])) for row in
                conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY rowid", (run_id,))]


def assert_failure(remote, run_id, error):
    client, app, bid, folder = remote
    settle(client, app, bid)
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] == "failed"
    assert build["report_url"] is None
    assert [data for kind, data in records(app, run_id) if kind == "build.finished"] == [
        {"status": "failed", "report_url": None, "version": 1}]
    with app.state.db.connect() as conn:
        rows = conn.execute("SELECT status,error FROM traces WHERE run_id=?", (run_id,)).fetchall()
    assert len(rows) == 1 and tuple(rows[0]) == ("error", error)


def test_ticket_claim_and_fixture_completion(remote, tmp_path):
    client, app, bid, folder = remote
    run_id = issue(client, bid)
    waiting = ticket(client, bid)
    shape(waiting, json.loads((HOSTED / "job_ticket.waiting.json").read_text()))
    assert waiting["state"] == "waiting" and waiting["claimed_at"] is None and waiting["run_id"] == run_id
    assert CODE_FORMAT.fullmatch(waiting["code"]) and waiting["build_id"] == bid and waiting["version"] == 1
    created = datetime.fromisoformat(waiting["expires_at"].replace("Z", "+00:00")) - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < created <= timedelta(minutes=30)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 409 and response.json()["error"]["code"] == "engine_busy"
    # No global lock: another build's run gets its own ticket and code.
    other, _ = make_build(client, app, tmp_path)
    other_run = issue(client, other)
    assert ticket(client, other)["code"] != waiting["code"]
    sloppy = waiting["code"].replace("-", "").lower()
    claimed = claim(client, sloppy).json()
    shape(claimed, json.loads((HOSTED / "claimed_job.json").read_text()))
    job = claimed["job"]
    assert job == dict(run_id=run_id, build_id=bid, version=1, dry_run=True, timeout_s=17,
                       files=["recipe.jsonl", "background_p1.png"]) and claimed["api_version"] == "3.4"
    TOKENS[run_id] = {"X-DSS-Job-Token": claimed["job_token"]}
    running = ticket(client, bid)
    shape(running, json.loads((HOSTED / "job_ticket.running.json").read_text()))
    assert running["state"] == "running" and running["claimed_at"] and running["code"] == waiting["code"]
    for name in job["files"]:
        response = client.get(f"/api/agent/jobs/{run_id}/files/{name}", headers=auth(run_id))
        assert response.status_code == 200 and response.content == (folder / name).read_bytes()
    screenshot = b"\x89PNG\r\n\x1a\nfixture"
    response = client.put(f"/api/agent/jobs/{run_id}/screens/s012_failed.png", headers=auth(run_id), content=screenshot)
    assert response.status_code == 200
    assert (folder / "screens/s012_failed.png").read_bytes() == screenshot
    post_events(client, run_id, EVENTS[:8])
    post_events(client, run_id, EVENTS[8:])
    finish(client, run_id)
    assert ticket(client, bid)["state"] == "finished"
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
        response = getattr(client, method)(f"/api/agent/jobs/{run_id}/{suffix}", headers=auth(run_id), **kwargs)
        assert response.status_code == 404 and response.json()["error"]["code"] == "job_not_found"
    # Only the token's SHA-256 is stored; the other build's ticket still waits for its own agent.
    raw = (tmp_path / "dss.sqlite").read_bytes()
    token = claimed["job_token"]
    assert token.encode() not in raw and hashlib.sha256(token.encode()).hexdigest().encode() in raw
    assert ticket(client, other)["state"] == "waiting" and ticket(client, other)["run_id"] == other_run


def test_claim_misses_are_slow_and_single_use(remote):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    code = ticket(client, bid)["code"]
    for attempt in (code, code.lower(), "ZZZZ-ZZZZ", "not a code", ""):
        started = time.monotonic()
        response = claim(client, attempt, 404)
        assert response.json()["error"]["code"] == "job_code_invalid"
        assert time.monotonic() - started >= 1
    assert ticket(client, bid)["state"] == "running"
    finish(client, run_id, 1)


@pytest.mark.parametrize("method,suffix,kwargs", [
    ("get", "files/recipe.jsonl", {}),
    ("put", "screens/a.png", {"content": b"png"}),
    ("post", "events", {"json": {"events": EVENTS}}),
    ("post", "finished", {"json": {"exit_code": 0, "stderr_tail": ""}}),
])
def test_job_token_required_per_run(remote, tmp_path, method, suffix, kwargs):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    other, _ = make_build(client, app, tmp_path)
    other_run, _ = accept(remote, other)
    for headers in ({}, auth(other_run), {"X-DSS-Job-Token": "wrong"}, {"X-DSS-Access-Code": CODE},
                    {"X-DSS-Agent-Token": auth(run_id)["X-DSS-Job-Token"]}):
        response = getattr(client, method)(f"/api/agent/jobs/{run_id}/{suffix}", headers=headers, **kwargs)
        assert response.status_code == 401 and response.json()["error"]["code"] == "agent_unauthorized"
    # Unknown runs are 401 too: the token is checked before the run is looked up.
    response = getattr(client, method)(f"/api/agent/jobs/r_missing/{suffix}", headers=auth(run_id), **kwargs)
    assert response.status_code == 401
    assert ticket(client, bid)["state"] == "running"
    finish(client, run_id, 1)
    finish(client, other_run, 1)


def test_retired_polling_routes(remote):
    client, app, bid, folder = remote
    for method, path, kwargs in (("post", "heartbeat", {"json": {"chrome_running": True, "signed_in": True,
                                                                   "agent_version": "test"}}),
                                 ("get", "jobs/next", {})):
        response = getattr(client, method)("/api/agent/" + path, **kwargs)
        assert response.status_code == 404
    status = client.get("/api/engine/status")
    check(status, "engine_status.json")
    assert status.json() == {"mode": "agent", "chrome_running": False, "signed_in": False,
                             "agent_connected": False, "agent_last_seen": None}
    assert client.get(f"/api/builds/{bid}/job").json()["error"]["code"] == "job_not_found"
    assert client.get("/api/builds/b_000000000000/job").json()["error"]["code"] == "build_not_found"


def test_running_app_sweeps_on_its_own(tmp_path, monkeypatch):
    from dss.agent import jobs
    monkeypatch.setattr(jobs, "SWEEP_INTERVAL_S", .05)
    app = agent_app(tmp_path)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        bid, _ = make_build(client, app, tmp_path)
        run_id = issue(client, bid)
        backdate(app, run_id, "expires_at", 1)
        for _ in range(200):
            if ticket(client, bid)["state"] == "expired":
                break
            time.sleep(.02)
        assert ticket(client, bid)["state"] == "expired"


def test_live_codes_are_unique_while_running(remote):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    code = ticket(client, bid)["code"]
    with app.state.db.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO agent_tickets(run_id,build_id,version,code,state,created_at,expires_at,job_json) "
                     "VALUES('r_000000000001',?,1,?,'waiting','x','x','{}')", (bid, code))
    finish(client, run_id, 1)


def test_waiting_ticket_expires_and_next_run_gets_new_code(remote):
    client, app, bid, folder = remote
    run_id = issue(client, bid)
    first = ticket(client, bid)["code"]
    sweep(client, app)
    assert ticket(client, bid)["state"] == "waiting"
    backdate(app, run_id, "expires_at", 1)
    sweep(client, app)
    assert_failure(remote, run_id, "job_expired")
    assert ticket(client, bid)["state"] == "expired"
    claim(client, first, 404)
    retry, _ = accept(remote)
    assert retry != run_id and ticket(client, bid)["code"] != first
    finish(client, retry, 1)


def test_running_ticket_times_out_without_events(remote):
    client, app, bid, folder = remote
    run_id, job = accept(remote)
    limit = job["timeout_s"] + 60
    backdate(app, run_id, "last_event_at", limit - 5)
    sweep(client, app)
    post_events(client, run_id, [EVENTS[0]])  # an event restarts the clock
    backdate(app, run_id, "last_event_at", limit - 5)
    sweep(client, app)
    assert ticket(client, bid)["state"] == "running"
    backdate(app, run_id, "last_event_at", limit)
    sweep(client, app)
    assert_failure(remote, run_id, "agent_timeout")
    assert ticket(client, bid)["state"] == "finished"
    response = client.post(f"/api/agent/jobs/{run_id}/events", headers=auth(run_id), json={"events": EVENTS})
    assert response.status_code == 404 and response.json()["error"]["code"] == "job_not_found"
    retry, _ = accept(remote)
    finish(client, retry, 1)


def test_restart_keeps_waiting_ticket_and_fails_running_one(tmp_path, monkeypatch):
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "17")
    app = agent_app(tmp_path)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        waiting_bid, folder = make_build(client, app, tmp_path)
        running_bid, _ = make_build(client, app, tmp_path)
        waiting_run = issue(client, waiting_bid)
        code = ticket(client, waiting_bid)["code"]
        running_run, _ = accept((client, app, running_bid, None))
    app = agent_app(tmp_path)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        assert_failure((client, app, running_bid, None), running_run, "agent_timeout")
        assert ticket(client, running_bid)["state"] == "finished"
        response = client.post(f"/api/agent/jobs/{running_run}/finished", headers=auth(running_run),
                               json={"exit_code": 0, "stderr_tail": ""})
        assert response.status_code == 404
        assert client.get(f"/api/builds/{waiting_bid}").json()["stage"] == "build"
        claimed = claim(client, code).json()
        assert claimed["job"]["run_id"] == waiting_run
        TOKENS[waiting_run] = {"X-DSS-Job-Token": claimed["job_token"]}
        assert client.get(f"/api/agent/jobs/{waiting_run}/files/recipe.jsonl",
                          headers=auth(waiting_run)).status_code == 200
        post_events(client, waiting_run)
        finish(client, waiting_run)
        settle(client, app)
        assert client.get(f"/api/builds/{waiting_bid}").json()["stage"] == "done"
        with app.state.db.connect() as conn:
            rows = conn.execute("SELECT status FROM traces WHERE run_id=?", (waiting_run,)).fetchall()
        assert [row[0] for row in rows] == ["ok"]


def test_codes_and_tokens_never_logged_or_traced(remote, caplog):
    caplog.set_level(logging.DEBUG)
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    code, token = ticket(client, bid)["code"], auth(run_id)["X-DSS-Job-Token"]
    post_events(client, run_id)
    finish(client, run_id)
    settle(client, app)
    with app.state.db.connect() as conn:
        stored = json.dumps([dict(row) for row in conn.execute("SELECT * FROM traces")] +
                            [dict(row) for row in conn.execute("SELECT * FROM events")])
    for secret in (code, code.replace("-", ""), token):
        assert secret not in caplog.text and secret not in stored and secret not in client.get("/api/traces").text


def test_local_mode_has_no_jobs(tmp_path):
    app = create_app(Config(data_dir=tmp_path), model_lister=fake_models)
    with TestClient(app) as client:
        bid = client.post("/api/builds", json={"archetype": "executive", "mode": "data"}).json()["id"]
        response = client.get(f"/api/builds/{bid}/job")
        assert response.status_code == 404 and response.json()["error"]["code"] == "agent_mode_off"
        response = client.post("/api/agent/claim", json={"code": "AAAA-AAAA", "agent_version": "test"})
        assert response.status_code == 404 and response.json()["error"]["code"] == "agent_mode_off"


@pytest.mark.parametrize("url", ["https://evil.example/report", "https://datastudio.google.com.evil.example/r",
    "http://datastudio.google.com/r", "https://user@lookerstudio.google.com/r", "https://[invalid", 12])
def test_invalid_url_never_persisted_and_releases_build(remote, url):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    event = {**EVENTS[-1], "report_url": url}
    post_events(client, run_id, [event])
    assert_failure(remote, run_id, "invalid_report_url")
    assert ticket(client, bid)["state"] == "finished"
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


@pytest.mark.parametrize("suffix", ["%2e%2e/dss.sqlite", "%2e%2e", "screens/x.png", "bad%5cname.png", "not-listed.png"])
def test_file_boundaries(remote, suffix):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    for method, segment in (("get", "files"), ("put", "screens")):
        if segment == "screens" and suffix == "not-listed.png":
            continue  # Any plain PNG name is allowed for screenshots.
        response = getattr(client, method)(f"/api/agent/jobs/{run_id}/{segment}/{suffix}", headers=auth(run_id))
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
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
    run_id, job = accept(remote)
    assert job["files"] == ["recipe.jsonl", "background_p1.png", "logo.png"]
    finish(client, run_id, 1)
    settle(client, app)
    add_images(folder, "../dss.sqlite")
    ready_fixture(app, bid, folder)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_name"
    assert not app.state.engine_tasks and ticket(client, bid)["state"] == "finished"


def test_secrets_redacted_from_events_and_stderr(remote, caplog):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    token = auth(run_id)["X-DSS-Job-Token"]
    text = f"{token} {CODE} fake-google-key"
    post_events(client, run_id, [{**EVENTS[2], "message": text}, EVENTS[-1]])
    finish(client, run_id, 0, text)
    serialized = json.dumps(records(app, run_id)) + (folder / "events.jsonl").read_text() + caplog.text
    for secret in (token, CODE, "fake-google-key"):
        assert secret not in serialized
    assert "[redacted]" in serialized


def test_login_settings_lock_and_deployment_overrides(remote):
    client, app, bid, folder = remote
    response = client.post("/api/engine/login")
    assert response.status_code == 409 and response.json()["error"]["code"] == "login_on_agent"
    for field in ("google_api_key", "gcp_project_id", "bq_dataset", "bq_location", "gcs_bucket"):
        response = client.put("/api/settings", json={field: "changed", "stages": {"routine": {"model": "gemini-3.8-flash"}}})
        assert response.status_code == 403 and response.json()["error"]["code"] == "settings_locked"
    response = client.put("/api/settings", json={"stages": {"native_planning": {"model": "gemini-4-argon"}, "routine": {"model": "gemini-3.8-flash"}}})
    assert response.status_code == 200 and response.json()["stages"]["routine"]["model"] == "gemini-3.8-flash"
    app.state.settings.update({"gcp_project_id": "old-local-project", "google_api_key": "old-key"})
    config = app.state.settings.get()
    assert config.gcp_project_id == "deployment" and config.google_api_key.get_secret_value() == "fake-google-key"


@pytest.mark.parametrize("mode,fixture", [("agent", "engine_status.json"), ("local", "engine_status.local.json")])
def test_status_contract_variants(tmp_path, monkeypatch, mode, fixture):
    from dss.api import engine
    async def fake_check(*args):
        return 0, '{"chrome_running": true, "signed_in": true}'
    monkeypatch.setattr(engine, "control_command", fake_check)
    app = create_app(Config(data_dir=tmp_path, engine_mode=mode), model_lister=fake_models)
    with TestClient(app) as client:
        check(client.get("/api/engine/status"), fixture)
        if mode == "local":
            for method, path in (("post", "claim"), ("put", "jobs/x/screens/a.png"), ("get", "unknown")):
                response = getattr(client, method)("/api/agent/" + path, headers={"X-DSS-Job-Token": "x"})
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
        app = create_app(Config(data_dir=tmp_path, engine_mode="agent"), model_lister=fake_models)
        with TestClient(app) as client:
            assert_failure((client, app, bid, tmp_path), run_id, "agent_timeout")
            assert client.get(f"/api/builds/{bid}/job").json()["error"]["code"] == "job_not_found"


def test_shutdown_leaves_live_ticket_for_next_start(remote):
    client, app, bid, folder = remote
    run_id, _ = accept(remote)
    async def close():
        await app.state.agent_jobs.close()
        tasks = tuple(app.state.engine_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    client.portal.call(close)
    assert not app.state.harness.active_builds and not app.state.engine_tasks
    # The ticket, stage and version wait for recover() on the next start (restart test).
    assert ticket(client, bid)["state"] == "running"
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "build" and build["versions"][0]["status"] == "building"


def job_recipe(client, run_id):
    response = client.get(f"/api/agent/jobs/{run_id}/files/recipe.jsonl", headers=auth(run_id))
    assert response.status_code == 200
    return response.content.decode("utf-8")


def test_job_ships_recipe_of_revised_spec(remote, monkeypatch):
    from test_revise import seed_revision, revise_through_api
    client, app, bid, folder = remote
    seed_revision(app, bid, monkeypatch)
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    stale = (folder / "recipe.jsonl").read_text(encoding="utf-8")
    revised = revise_through_api(client, app, bid)
    run_id, job = accept(remote)
    shipped = job_recipe(client, run_id)
    assert shipped == compile_recipe(revised, 1) and shipped != stale
    chart = json.loads(shipped.split("\n")[5])  # after open_report, rename_page, canvas, background
    assert chart["component_id"] == "p1_revenue" and chart["title"] == "Net revenue" and chart["w"] > 568
    post_events(client, run_id)
    finish(client, run_id)
    settle(client, app)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "done"


def test_refresh_failure_queues_no_job(remote):
    client, app, bid, folder = remote
    previous, good = (folder / "recipe.jsonl").read_bytes(), (folder / "spec.json").read_text()
    add_images(folder, None)  # an image without a path cannot compile
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 409 and response.json()["error"]["code"] == "feasibility_blocked"
    assert client.get(f"/api/builds/{bid}/job").status_code == 404
    assert not app.state.agent_jobs.running and not app.state.engine_tasks
    assert bid not in app.state.harness.active_builds
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
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
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
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
    originals = {path: (folder / path).read_bytes() for path in [*NESTED, "background_p1.png"]}
    run_id, job = accept(remote)
    canonical = compile_recipe(DashboardSpec.model_validate_json((folder / "spec.json").read_text()), 1)
    assert (folder / "recipe.jsonl").read_bytes() == canonical.encode("utf-8")  # canonical bytes kept
    files = job["files"]
    assert files[0] == "recipe.jsonl" and len(files) == len(set(f.casefold() for f in files)) == 6
    assert all(PLAIN.fullmatch(name) and name not in (".", "..") for name in files)
    assert files[1] == "background_p1.png" and "logo.png" in files
    downloaded = {name: client.get(f"/api/agent/jobs/{run_id}/files/{name}", headers=auth(run_id)) for name in files}
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
    from fakes import ready_fixture
    ready_fixture(app, bid, folder)
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == (400 if code == "invalid_name" else 422), response.text
    assert response.json()["error"]["code"] == code
    assert client.get(f"/api/builds/{bid}/job").status_code == 404
    assert not app.state.agent_jobs.running and not app.state.agent_jobs.jobs and not app.state.engine_tasks
    assert bid not in app.state.harness.active_builds
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] != "building"
    (folder / "spec.json").write_text(good, encoding="utf-8")
    ready_fixture(app, bid, folder)
    run_id, job = accept(remote)  # the stage and lock are still usable
    assert job["files"] == ["recipe.jsonl", "background_p1.png"]
    finish(client, run_id, 1)
    settle(client, app)
