"""The real dss-agent against a live agent-mode uvicorn on a free port."""
import asyncio
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest
import uvicorn

from dss.agent import client
from dss.config import Config
from dss.harness.guardrails import RunError
from dss.harness.nodes.execute import terminate_tree
from dss.main import create_app
from dss.recipe.compiler import compile_recipe
from dss.spec.models import DashboardSpec
from fakes import fake_models

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FAKE = ROOT / "tests/fake_engine.py"
TOKEN = "agent-client-token-at-least-24"
CODE = "agent-client-access-code"
JOB = json.loads((REPO / "contracts/fixtures/api/agent_job.json").read_text())

# A faked dsengine: logs every check and run, otherwise delegates to tests/fake_engine.py.
WRAPPER = r'''
import json, os, subprocess, sys, time
def note(kind):
    with open(os.environ["DSS_TEST_ENGINE_LOG"], "a") as log:
        log.write(json.dumps({"kind": kind, "t": time.time(), "cwd": os.getcwd()}) + "\n")
def finished(op_id, screenshot):
    print(json.dumps({"event": "op_finished", "ts": "2026-10-19T00:00:00Z", "op_id": op_id, "op": "set_style",
                      "status": "failed", "message": "", "screenshot": screenshot, "duration_ms": 1}), flush=True)
def tick(mark):
    with open(os.environ["DSS_TEST_ENGINE_ALIVE"], "a") as alive:
        alive.write(mark)
if sys.argv[1] == "check":
    note("check")
    print(json.dumps({"chrome_running": True, "signed_in": False}))
    sys.exit(0)
note("run_started")
if os.environ.get("DSS_TEST_ENGINE_TRICKLE"):
    # A child that inherits stdout: only a process-tree kill ends the pipe.
    child = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('c')\n    time.sleep(.05)"
    subprocess.Popen([sys.executable, "-c", child, os.environ["DSS_TEST_ENGINE_ALIVE"]])
    while True:
        tick("e")
        print(json.dumps({"event": "log", "ts": "2026-10-19T00:00:00Z", "level": "info", "message": "working"}), flush=True)
        time.sleep(.1)
if os.environ.get("DSS_TEST_ENGINE_SHOT"):
    screens = sys.argv[sys.argv.index("--screens") + 1]
    with open(os.path.join(screens, "s900_shot.png"), "wb") as shot:
        shot.write(b"\x89PNG shot")
    finished("s900", "s900_shot.png")
    finished("s901", "../escape.png")
    note("shot_emitted")
time.sleep(float(os.environ.get("DSS_TEST_ENGINE_SLEEP", "0")))
code = subprocess.call([sys.executable, os.environ["DSS_TEST_FAKE_ENGINE"], *sys.argv[1:]])
note("run_finished")
sys.exit(code)
'''


class LiveServer:
    """uvicorn in a thread on a socket bound up front (refuses connections until started)."""

    def __init__(self, data):
        data.mkdir(parents=True, exist_ok=True)
        self.data = data
        self.app = create_app(Config(data_dir=data, engine_mode="agent", access_code=CODE, agent_token=TOKEN),
                              model_lister=fake_models)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_config=None, log_level="warning",
                                                    timeout_graceful_shutdown=2))
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=lambda: self.loop.run_until_complete(self.server.serve([self.sock])),
                                       daemon=True)
        self.api = httpx.Client(base_url=self.url, headers={"X-DSS-Access-Code": CODE}, timeout=10)

    def start(self):
        self.thread.start()
        wait_for(lambda: self.server.started, "server start")

    def stop(self):
        self.api.close()
        if self.thread.is_alive():
            self.server.should_exit = True
            self.thread.join(15)
        self.sock.close()

    def call(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(5)

    def queue_build(self):
        bid = self.api.post("/api/builds", json={"archetype": "executive", "mode": "data"}).json()["id"]
        folder = self.data / "builds" / bid / "v1"
        folder.mkdir(parents=True, exist_ok=True)
        spec = DashboardSpec.model_validate_json((ROOT / "tests/data/thin_spec.json").read_text())
        spec.build_id = bid
        (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
        (folder / "recipe.jsonl").write_text(compile_recipe(spec, 1), encoding="utf-8", newline="\n")
        (folder / "background_p1.png").write_bytes(b"fake-background")
        with self.app.state.db.connect() as conn:
            conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (bid,))
        return bid, folder

    def run(self, bid):
        wait_for(lambda: self.api.get("/api/engine/status").json()["agent_connected"], "agent heartbeat")
        response = self.api.post(f"/api/builds/{bid}/run")
        assert response.status_code == 202, response.text
        return response.json()["run_id"]

    def finished(self, bid):
        wait_for(lambda: self.api.get(f"/api/builds/{bid}").json()["stage"] != "build", "build end", 30)
        return self.api.get(f"/api/builds/{bid}").json()


def wait_for(predicate, what, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    pytest.fail(f"timed out waiting for {what}")


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "19")
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "0")
    live = LiveServer(tmp_path / "server")
    live.start()
    yield live
    live.stop()


@pytest.fixture
def wrapper(tmp_path, monkeypatch):
    script = tmp_path / "engine.py"
    script.write_text(WRAPPER, encoding="utf-8")
    monkeypatch.setenv("DSS_TEST_ENGINE_LOG", str(tmp_path / "engine.log"))
    monkeypatch.setenv("DSS_TEST_ENGINE_ALIVE", str(tmp_path / "alive"))
    monkeypatch.setenv("DSS_TEST_FAKE_ENGINE", str(FAKE))
    return script


@pytest.fixture
def fast(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    for name, value in (("HEARTBEAT_S", .1), ("CHECK_S", .8), ("POLL_WAIT_S", .6), ("BACKOFF_S", .05),
                        ("BACKOFF_MAX_S", .2)):
        monkeypatch.setattr(client, name, value)


@contextmanager
def running(agent):
    result = {}
    thread = threading.Thread(target=lambda: result.update(code=agent.run()), daemon=True)
    thread.start()
    try:
        yield thread, result
    finally:
        agent.stop.set()
        thread.join(15)


def notes(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def assert_no_token(*texts):
    assert texts and all(TOKEN not in text for text in texts)


@pytest.mark.parametrize("cwd,dry_run", [(REPO, True), (ROOT, False)], ids=["repo-root-dry-run", "backend"])
def test_console_script_takes_queued_build_to_done(server, cwd, dry_run):
    script = shutil.which("dss-agent", path=str(Path(sys.executable).parent))
    assert script, "uv sync installs the dss-agent console script"
    env = {**os.environ, "DSS_AGENT_TOKEN": TOKEN, "DSS_ENGINE_CMD": f'"{sys.executable}" "{FAKE}"',
           "DSS_DATA_DIR": "", "DSS_AGENT_SERVER": "", "PYTHONUNBUFFERED": "1"}
    agent = subprocess.Popen([script, "--server", server.url] + ["--dry-run"] * dry_run, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=os.name != "nt")
    lines = []
    reader = threading.Thread(target=lambda: [lines.append(line) for line in agent.stdout], daemon=True)
    reader.start()
    bid = None
    try:
        bid, source = server.queue_build()
        server.run(bid)
        build = server.finished(bid)
        assert build["stage"] == "done" and build["versions"][0]["status"] == "published"
        status = server.api.get("/api/engine/status").json()
        assert status["chrome_running"] and status["signed_in"]
        folder = (REPO / "data/agent" / bid / "v1").resolve()
        for name in ("recipe.jsonl", "background_p1.png"):
            assert (folder / name).read_bytes() == (source / name).read_bytes()
        flags = json.loads((folder / "fake-args.json").read_text())
        assert flags[flags.index("--timeout") + 1] == "19"
        assert Path(flags[flags.index("--screens") + 1]) == folder / "screens"
        assert ("--dry-run" in flags) is dry_run
        wait_for(lambda: "finished (exit code 0)" in "".join(lines), "the agent's job report")
    finally:
        terminate_tree(agent)
        agent.wait(15)
        reader.join(15)
        if bid:
            shutil.rmtree(REPO / "data/agent" / bid, ignore_errors=True)
    output = "".join(lines)
    assert "Connected to " + server.url in output
    assert_no_token(output)


def test_heartbeats_during_polls_and_runs_and_checks_only_while_idle(server, wrapper, fast, tmp_path,
                                                                     monkeypatch, caplog, capfd):
    monkeypatch.setenv("DSS_TEST_ENGINE_SLEEP", "1.5")
    jobs, beats, polls = server.app.state.agent_jobs, [], []
    heartbeat, poll = jobs.heartbeat, jobs.next
    def record_beat(chrome_running, signed_in):
        beats.append((time.time(), chrome_running, signed_in))
        heartbeat(chrome_running, signed_in)
    async def record_poll(wait):
        started = time.time()
        try:
            return await poll(wait)
        finally:
            polls.append((started, time.time()))
    jobs.heartbeat, jobs.next = record_beat, record_poll
    agent = client.Agent(server.url, TOKEN, tmp_path / "data", [sys.executable, str(wrapper)])
    log = tmp_path / "engine.log"
    with running(agent) as (thread, result):
        wait_for(lambda: beats, "first heartbeat")
        assert notes(log)[0]["kind"] == "check" and notes(log)[0]["t"] < beats[0][0]
        status = server.api.get("/api/engine/status").json()
        assert status["chrome_running"] and not status["signed_in"]
        time.sleep(1.4)
        bid, _ = server.queue_build()
        server.run(bid)
        assert server.finished(bid)["stage"] == "done"
        wait_for(lambda: [n for n in notes(log) if n["kind"] == "check" and n["t"] > run_end(log)],
                 "an idle check after the run")
        assert thread.is_alive()
    assert result["code"] == 0
    started = next(n["t"] for n in notes(log) if n["kind"] == "run_started")
    checks = [n["t"] for n in notes(log) if n["kind"] == "check"]
    assert len([t for t in checks if t < started]) >= 2
    assert not [t for t in checks if started <= t <= run_end(log)]
    assert len([b for b in beats if started < b[0] < run_end(log)]) >= 5
    long_polls = [(a, b) for a, b in polls if b - a >= .4]
    assert any(len([beat for beat in beats if a < beat[0] < b]) >= 3 for a, b in long_polls)
    assert all(beat[1:] == (True, False) for beat in beats)
    assert_no_token(caplog.text, *capfd.readouterr())


def run_end(log):
    return next((n["t"] for n in notes(log) if n["kind"] == "run_finished"), float("inf"))


def test_screenshots_upload_before_their_events_flushed_within_a_second(server, wrapper, fast, tmp_path,
                                                                        monkeypatch, caplog, capfd):
    monkeypatch.chdir(tmp_path)  # the engine must still start in backend/
    monkeypatch.setenv("DSS_TEST_ENGINE_SHOT", "1")
    monkeypatch.setenv("DSS_TEST_ENGINE_SLEEP", "2")
    jobs, batches = server.app.state.agent_jobs, []
    post = jobs.events
    async def record_events(run_id, events):
        shots = [path.read_bytes() for path in server.data.glob("builds/*/v1/screens/*")]
        batches.append((time.time(), [event.get("op_id") for event in events], shots))
        return await post(run_id, events)
    jobs.events = record_events
    agent = client.Agent(server.url, TOKEN, tmp_path / "data", [sys.executable, str(wrapper)])
    with running(agent):
        bid, source = server.queue_build()
        server.run(bid)
        assert server.finished(bid)["stage"] == "done"
    log = tmp_path / "engine.log"
    assert {Path(n["cwd"]).resolve() for n in notes(log)} == {ROOT}
    emitted = next(n["t"] for n in notes(log) if n["kind"] == "shot_emitted")
    arrived, op_ids, shots = next(batch for batch in batches if "s900" in batch[1])
    assert op_ids == ["s900", "s901"] and arrived - emitted < 1.5 and arrived < run_end(log)
    assert shots == [b"\x89PNG shot"]
    assert [path.name for path in (source / "screens").iterdir()] == ["s900_shot.png"]
    assert "skipped a screenshot" in caplog.text
    assert_no_token(caplog.text, *capfd.readouterr())


def test_job_not_found_mid_job_kills_engine_tree_and_deletes_folder(server, wrapper, fast, tmp_path,
                                                                    monkeypatch, caplog, capfd):
    monkeypatch.setenv("DSS_TEST_ENGINE_TRICKLE", "1")
    alive = tmp_path / "alive"
    agent = client.Agent(server.url, TOKEN, tmp_path / "data", [sys.executable, str(wrapper)])
    with running(agent) as (thread, result):
        bid, source = server.queue_build()
        run_id = server.run(bid)
        folder = tmp_path / "data/agent" / bid / "v1"
        wait_for(lambda: "working" in (source / "events.jsonl").read_text(), "events relayed")
        wait_for(lambda: alive.exists() and "c" in alive.read_text(), "engine child")
        assert (folder / "recipe.jsonl").is_file()
        jobs = server.app.state.agent_jobs
        async def expire():
            # The server's own timeout path: the job is completed and forgotten.
            job = jobs.get(run_id)
            async with job.lock:
                jobs.complete(job, 1, RunError("agent_timeout", "Build agent timed out", 504))
        server.call(expire())
        wait_for(lambda: not folder.exists(), "job folder removal")
        size = alive.stat().st_size
        time.sleep(.5)
        assert alive.stat().st_size == size
        build = server.finished(bid)
        assert build["stage"] == "prototype" and build["versions"][0]["status"] == "failed"
        assert thread.is_alive() and not server.app.state.engine_busy
        retry = server.queue_build()[0]
        monkeypatch.delenv("DSS_TEST_ENGINE_TRICKLE")
        server.run(retry)
        assert server.finished(retry)["stage"] == "done"
    assert result["code"] == 0
    assert f"Job {run_id} no longer exists" in caplog.text
    assert_no_token(caplog.text, *capfd.readouterr())


def test_network_errors_retry_with_backoff_then_exit_nonzero(tmp_path, fast, monkeypatch, caplog, capfd):
    assert client.RETRY_BUDGET_S == 60
    monkeypatch.setattr(client, "RETRY_BUDGET_S", 20)
    live = LiveServer(tmp_path / "server")
    agent = client.Agent(live.url, TOKEN, tmp_path / "data", [sys.executable, str(FAKE)])
    try:
        with running(agent) as (thread, result):
            wait_for(lambda: "retrying" in caplog.text, "a refused request", 15)
            live.start()
            wait_for(lambda: live.app.state.agent_jobs.connected, "reconnect", 15)
            monkeypatch.setattr(client, "RETRY_BUDGET_S", 1)
            stopped = time.monotonic()
            live.stop()
            thread.join(30)
            assert not thread.is_alive()
            assert time.monotonic() - stopped >= 1
    finally:
        live.stop()
    assert result["code"] == 1
    assert "Server unavailable for 1 s" in caplog.text
    assert_no_token(caplog.text, *capfd.readouterr())


def test_backoff_doubles_and_429_or_5xx_retry_until_the_budget(tmp_path, monkeypatch):
    for name, value in (("BACKOFF_S", .05), ("BACKOFF_MAX_S", .2), ("RETRY_BUDGET_S", .6)):
        monkeypatch.setattr(client, name, value)
    agent = client.Agent("http://127.0.0.1:1", TOKEN, tmp_path, ["dsengine"])
    delays, wait = [], agent.stop.wait
    agent.stop.wait = lambda seconds: delays.append(seconds) or wait(seconds)
    def mock(handler):
        return httpx.Client(base_url=agent.server, transport=httpx.MockTransport(handler))
    codes = [429, 503, 204]
    assert agent.call(mock(lambda request: httpx.Response(codes.pop(0))), "GET", "/jobs/next").status_code == 204
    assert delays == [.05, .1]
    delays.clear()
    with pytest.raises(client.AgentExit) as error:
        agent.call(mock(lambda request: httpx.Response(500)), "GET", "/jobs/next")
    assert error.value.code == 1 and delays[:3] == [.05, .1, .2] and max(delays) == .2


@pytest.mark.parametrize("response,code", [
    (httpx.Response(200, text="<!doctype html>"), 1), (httpx.Response(401), 2),
    (httpx.Response(404, json={"error": {"code": "agent_mode_off", "message": "", "detail": {}}}), 2)])
def test_misconfigured_server_exits_instead_of_looping(tmp_path, monkeypatch, response, code):
    agent = client.Agent("http://127.0.0.1:1", TOKEN, tmp_path, [sys.executable, str(FAKE)])
    def handler(request):
        return httpx.Response(200, json={"ok": True}) if request.url.path.endswith("/heartbeat") else response
    monkeypatch.setattr(agent, "http", lambda: httpx.Client(base_url=agent.server, transport=httpx.MockTransport(handler)))
    assert agent.run() == code


def test_timeouts_engine_arguments_and_job_validation(tmp_path):
    assert (client.HEARTBEAT_S, client.CHECK_S, client.POLL_WAIT_S, client.FLUSH_S) == (10, 60, 25, 1)
    assert client.HTTP_TIMEOUT_S > client.POLL_WAIT_S + 10
    agent = client.Agent("http://127.0.0.1:1", TOKEN, tmp_path, ["dsengine"])
    with agent.http() as http:
        assert http.timeout.read == client.HTTP_TIMEOUT_S
    folder = agent.folder(JOB)
    assert folder == tmp_path / "agent" / JOB["build_id"] / "v1"
    plain = ["dsengine", "run", str(folder / "recipe.jsonl"), "--timeout", "600", "--screens", str(folder / "screens")]
    assert agent.engine_args(JOB, folder) == plain
    assert agent.engine_args({**JOB, "dry_run": True}, folder) == plain[:5] + ["--dry-run"] + plain[5:]
    agent.dry_run = True
    assert agent.engine_args(JOB, folder) == plain[:5] + ["--dry-run"] + plain[5:]
    for bad in ({"build_id": "../b_3f9a0c12d4e5"}, {"build_id": "b_3F9A0C12D4E5"}, {"version": 0},
                {"version": True}, {"version": "1"}, {"timeout_s": -1}, {"dry_run": "yes"},
                {"files": ["background_p1.png"]}, {"files": ["recipe.jsonl", "../dss.sqlite"]},
                {"files": ["recipe.jsonl", "a/b.png"]}, {"files": ["recipe.jsonl", ".."]},
                {"files": ["recipe.jsonl", "screens"]}, {"files": []}):
        with pytest.raises(ValueError):
            agent.folder({**JOB, **bad})


def test_configuration_resolves_from_backend_whatever_the_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DSS_AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("DSS_DATA_DIR", "")
    monkeypatch.setenv("DSS_AGENT_SERVER", "https://dss-abc123-as.a.run.app/")
    monkeypatch.setenv("DSS_ENGINE_CMD", f'"{sys.executable}" "{FAKE}"')
    agent = client.Agent.from_env()
    assert agent.server == "https://dss-abc123-as.a.run.app"
    assert agent.data_dir == (REPO / "data").resolve() and agent.command == [sys.executable, str(FAKE)]
    assert client.Agent.from_env("http://localhost:8000").server == "http://localhost:8000"
    monkeypatch.setenv("DSS_DATA_DIR", "../data/elsewhere")
    assert client.Agent.from_env().data_dir == (REPO / "data/elsewhere").resolve()
    for server in ("http://example.com", "https://dss.a.run.app/builds", "https://dss.a.run.app?x=1"):
        with pytest.raises(client.AgentExit) as error:
            client.Agent.from_env(server)
        assert error.value.code == 2
    for token in ("", TOKEN + "\n", TOKEN + "é"):
        monkeypatch.setenv("DSS_AGENT_TOKEN", token)
        with pytest.raises(client.AgentExit) as error:
            client.Agent.from_env()
        assert error.value.code == 2 and (not token or TOKEN not in str(error.value))
    monkeypatch.setenv("DSS_AGENT_TOKEN", TOKEN)
    assert client.main(["--server", "ftp://example.com"]) == 2
    assert client.main(["--server", "http://localhost:8000", "--token", TOKEN]) == 2
    assert_no_token(*capsys.readouterr())
