"""The real dss-agent (`dss-agent run --server --job`) against a live agent-mode uvicorn on a free port."""
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

from dss.agent import client, jobs as server_jobs
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
if os.environ.get("DSS_TEST_ENGINE_INPUTS"):
    # What the engine sees: every op path, resolved next to the recipe like dsengine does.
    recipe = sys.argv[2]
    with open(recipe, encoding="utf-8", newline="") as text:
        ops = [json.loads(line) for line in text.read().split("\n")[1:-1]]
    seen = {}
    for op in ops:
        if "path" in op:
            with open(os.path.join(os.path.dirname(recipe), op["path"]), "rb") as asset:
                seen[op["id"]] = [op["path"], asset.read().decode("latin-1")]
    with open(os.environ["DSS_TEST_ENGINE_INPUTS"], "w") as out:
        json.dump(seen, out)
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
args = [sys.executable, os.environ["DSS_TEST_FAKE_ENGINE"], *sys.argv[1:]]
if os.environ.get("DSS_TEST_ENGINE_REPORT"):
    # A real run's run_finished names the report; the fake engine's has none.
    engine = subprocess.Popen(args, stdout=subprocess.PIPE, text=True)
    for line in engine.stdout:
        event = json.loads(line)
        if event.get("event") == "run_finished":
            event["report_url"] = os.environ["DSS_TEST_ENGINE_REPORT"]
        print(json.dumps(event), flush=True)
    code = engine.wait()
else:
    code = subprocess.call(args)
note("run_finished")
sys.exit(code)
'''


class LiveServer:
    """uvicorn in a thread on a socket bound up front (refuses connections until started)."""

    def __init__(self, data):
        data.mkdir(parents=True, exist_ok=True)
        self.data = data
        self.app = create_app(Config(data_dir=data, engine_mode="agent", access_code=CODE),
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
        from fakes import ready_fixture
        ready_fixture(self.app, bid, folder)
        return bid, folder

    def ticket(self, bid):
        return self.api.get(f"/api/builds/{bid}/job").json()

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
    for name, value in (("BACKOFF_S", .05), ("BACKOFF_MAX_S", .2)):
        monkeypatch.setattr(client, name, value)


@pytest.fixture
def visitor(tmp_path, monkeypatch):
    """A visitor's machine as the setup leaves it: a cwd with no .env, no DSS_AGENT_TOKEN, and only
    DSS_DATA_DIR and DSS_ENGINE_CMD set. Returns a setter for the engine script."""
    home = tmp_path / "visitor"
    home.mkdir()
    monkeypatch.chdir(home)
    for name in ("DSS_AGENT_TOKEN", "DSS_AGENT_SERVER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DSS_DATA_DIR", str(tmp_path / "data"))
    def engine(script):
        monkeypatch.setenv("DSS_ENGINE_CMD", f'"{sys.executable}" "{script}"')
    engine(FAKE)
    return engine


def issue(server, bid):
    """POST /run and the code the Build stage shows (GET .../job)."""
    response = server.api.post(f"/api/builds/{bid}/run")
    assert response.status_code == 202, response.text
    return response.json()["run_id"], server.ticket(bid)["code"]


def record_tokens(server):
    """The job tokens the server hands out, so the tests can look for them in output and files."""
    manager, tokens = server.app.state.agent_jobs, []
    claim = manager.claim
    async def recording(code):
        claimed = await claim(code)
        tokens.append(claimed["job_token"])
        return claimed
    manager.claim = recording
    return tokens


def agent_run(server, code, *flags):
    return client.main(["run", "--server", server.url, "--job", code, *flags])


@contextmanager
def in_thread(function, *args):
    result = {}
    thread = threading.Thread(target=lambda: result.update(code=function(*args)), daemon=True)
    thread.start()
    try:
        yield thread, result
    finally:
        thread.join(30)


def notes(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def assert_no_token(*texts, secrets=(TOKEN,)):
    assert texts and all(secret not in text for secret in secrets for text in texts)


def assert_kept_secret(secrets, capsys, caplog, data):
    """Neither the code (as shown or typed without its dash) nor the job token reaches stdout, stderr,
    the log or any file the agent leaves under data/agent/."""
    secrets = [form for secret in secrets for form in (secret, secret.replace("-", ""))]
    assert secrets and all(secrets)
    out, err = capsys.readouterr()
    files = [path.read_bytes() for path in (data / "agent").rglob("*") if path.is_file()]
    for secret in secrets:
        assert secret not in out and secret not in err and secret not in caplog.text
        assert all(secret.encode() not in content for content in files)


def test_bare_and_polling_forms_exit_2_naming_run(server, visitor, capsys):
    """The 5.3 polling agent is gone: its bare form and its --server-only form print the usage of
    `run` and exit 2, and the installed console script does the same; nothing is claimed."""
    script = shutil.which("dss-agent", path=str(Path(sys.executable).parent))
    assert script, "uv sync installs the dss-agent console script"
    bid, _ = server.queue_build()
    _, code = issue(server, bid)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    for argv in ([], ["--server", server.url]):
        agent = subprocess.run([script, *argv], env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
        assert agent.returncode == 2 and client.USAGE in agent.stdout, agent.stdout + agent.stderr
        assert client.main(argv) == 2
    # Malformed lines print the usage without echoing what was typed (it may be the code).
    for argv in ([code], ["run", "--server", server.url], ["run", "--job", code],
                 ["run", "--server", server.url, "--job", code, "--token", code]):
        assert client.main(argv) == 2
    assert server.ticket(bid)["state"] == "waiting"
    out, err = capsys.readouterr()
    assert out.count(client.USAGE) == 6 and code not in out + err


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "real"])
def test_run_claims_runs_reports_and_prints_the_report_link(server, visitor, wrapper, tmp_path, monkeypatch,
                                                            caplog, capsys, dry_run):
    caplog.set_level(logging.INFO)
    visitor(wrapper)
    monkeypatch.setenv("DSS_TEST_ENGINE_SHOT", "1")
    report = "https://datastudio.google.com/reporting/00000000-0000-0000-0000-000000000000/page/p_1"
    if not dry_run:
        monkeypatch.setenv("DSS_TEST_ENGINE_REPORT", report)
    tokens = record_tokens(server)
    bid, source = server.queue_build()
    run_id, code = issue(server, bid)
    assert agent_run(server, code, *(["--dry-run"] if dry_run else [])) == 0
    build = server.finished(bid)
    assert build["stage"] == "done" and build["versions"][0]["status"] == "published"
    assert server.ticket(bid)["state"] == "finished" and len(tokens) == 1
    # Job.files downloaded into data/agent/<build_id>/v<n>/.
    folder = tmp_path / "data/agent" / bid / "v1"
    for name in ("recipe.jsonl", "background_p1.png"):
        assert (folder / name).read_bytes() == (source / name).read_bytes()
    # The engine: an argument list, started in backend/ whatever the cwd.
    assert {Path(n["cwd"]).resolve() for n in notes(tmp_path / "engine.log")} == {ROOT}
    flags = json.loads((folder / "fake-args.json").read_text())
    assert flags[flags.index("--timeout") + 1] == "19"
    assert Path(flags[flags.index("--screens") + 1]) == folder / "screens"
    assert ("--dry-run" in flags) is dry_run
    # The events in the engine's order, the screenshot an event names, then finished.
    ops = [json.loads(line)["id"] for line in (source / "recipe.jsonl").read_text(encoding="utf-8").splitlines()[1:]]
    expected = [("op_finished", "s900"), ("op_finished", "s901"), ("run_started", None),
                *[(kind, op) for op in ops for kind in ("op_started", "op_finished")], ("run_finished", None)]
    relayed = [json.loads(line) for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(event["event"], event.get("op_id")) for event in relayed] == expected
    assert (source / "screens/s900_shot.png").read_bytes() == b"\x89PNG shot"
    assert f"Job {run_id} finished (exit code 0)" in caplog.text
    out = capsys.readouterr().out
    assert (f"Report: {report}" in out) is not dry_run
    assert ("Dry run finished" in out) is dry_run
    print(out)  # back to capsys for the secret check
    assert_kept_secret([code, *tokens], capsys, caplog, tmp_path / "data")


def run_end(log):
    return next((n["t"] for n in notes(log) if n["kind"] == "run_finished"), float("inf"))


def test_screenshots_upload_before_their_events_flushed_within_a_second(server, visitor, wrapper, fast, tmp_path,
                                                                        monkeypatch, caplog, capsys):
    visitor(wrapper)
    monkeypatch.setenv("DSS_TEST_ENGINE_SHOT", "1")
    monkeypatch.setenv("DSS_TEST_ENGINE_SLEEP", "2")
    manager, batches, tokens = server.app.state.agent_jobs, [], record_tokens(server)
    post = manager.events
    async def record_events(run_id, events):
        shots = [path.read_bytes() for path in server.data.glob("builds/*/v1/screens/*")]
        batches.append((time.time(), [event.get("op_id") for event in events], shots))
        return await post(run_id, events)
    manager.events = record_events
    bid, source = server.queue_build()
    _, code = issue(server, bid)
    assert agent_run(server, code) == 0
    assert server.finished(bid)["stage"] == "done"
    log = tmp_path / "engine.log"
    emitted = next(n["t"] for n in notes(log) if n["kind"] == "shot_emitted")
    arrived, op_ids, shots = next(batch for batch in batches if "s900" in batch[1])
    assert op_ids == ["s900", "s901"] and arrived - emitted < 1.5 and arrived < run_end(log)
    assert shots == [b"\x89PNG shot"]
    assert [path.name for path in (source / "screens").iterdir()] == ["s900_shot.png"]
    assert "skipped a screenshot" in caplog.text
    assert_kept_secret([code, *tokens], capsys, caplog, tmp_path / "data")


def test_used_or_unknown_code_exits_1(server, visitor, tmp_path, caplog, capsys):
    bid, _ = server.queue_build()
    _, code = issue(server, bid)
    claimed = httpx.post(server.url + "/api/agent/claim", json={"code": code, "agent_version": "test"}, timeout=10)
    assert claimed.status_code == 200
    for attempt in (code, code.lower().replace("-", " "), "ABCD-EFGH"):
        assert agent_run(server, attempt) == 1
    out = capsys.readouterr().out
    assert out.count(client.CODE_INVALID) == 3 and not (tmp_path / "data/agent").exists()
    print(out)
    assert_kept_secret([code, "ABCD-EFGH"], capsys, caplog, tmp_path / "data")


def test_claim_with_another_api_version_exits_2(server, visitor, tmp_path, monkeypatch, caplog, capsys):
    monkeypatch.setattr(server_jobs, "API_VERSION", "9.9")  # the server's; the agent keeps its own
    tokens = record_tokens(server)
    bid, _ = server.queue_build()
    _, code = issue(server, bid)
    assert agent_run(server, code) == 2
    out = capsys.readouterr().out
    assert client.UPDATE in out
    print(out)  # back to capsys for the secret check
    assert not (tmp_path / "data/agent").exists()
    # It still ended the claimed ticket, so the next Build needn't wait out the server's timeout.
    assert server.finished(bid)["stage"] == "prototype" and server.ticket(bid)["state"] == "finished"
    assert_kept_secret([code, *tokens], capsys, caplog, tmp_path / "data")


def test_job_not_found_mid_job_kills_engine_tree_deletes_folder_exits_1(server, visitor, wrapper, fast, tmp_path,
                                                                         monkeypatch, caplog, capsys):
    visitor(wrapper)
    monkeypatch.setenv("DSS_TEST_ENGINE_TRICKLE", "1")
    alive, tokens = tmp_path / "alive", record_tokens(server)
    bid, source = server.queue_build()
    run_id, code = issue(server, bid)
    folder = tmp_path / "data/agent" / bid / "v1"
    with in_thread(agent_run, server, code) as (thread, result):
        wait_for(lambda: (source / "events.jsonl").is_file() and "working" in (source / "events.jsonl").read_text(),
                 "events relayed")
        wait_for(lambda: alive.exists() and "c" in alive.read_text(), "engine child")
        assert (folder / "recipe.jsonl").is_file()
        manager = server.app.state.agent_jobs
        async def expire():
            # The sweep's agent_timeout path: the ticket ends and the job is completed and forgotten.
            held = manager.get(run_id)
            async with held.lock:
                manager.close_ticket(run_id)
                manager.complete(held, 1, RunError("agent_timeout", "Build agent timed out", 504))
        server.call(expire())
        thread.join(15)
    assert result == {"code": 1} and not folder.exists()
    size = alive.stat().st_size
    time.sleep(.5)
    assert alive.stat().st_size == size  # engine and its child are gone
    build = server.finished(bid)
    assert build["stage"] == "prototype" and build["versions"][0]["status"] == "failed"
    assert not server.app.state.engine_busy
    out = capsys.readouterr().out
    assert f"Job {run_id} no longer exists" in out
    print(out)
    assert_kept_secret([code, *tokens], capsys, caplog, tmp_path / "data")


def test_nested_image_inputs_reach_the_engine_as_plain_files(server, visitor, wrapper, fast, tmp_path, monkeypatch,
                                                             caplog, capsys):
    from test_agent_server import nested_inputs
    visitor(wrapper)
    seen = tmp_path / "inputs.json"
    monkeypatch.setenv("DSS_TEST_ENGINE_INPUTS", str(seen))
    tokens = record_tokens(server)
    bid, source = server.queue_build()
    nested_inputs(source)
    from fakes import ready_fixture
    ready_fixture(server.app, bid, source)
    _, code = issue(server, bid)
    assert agent_run(server, code) == 0
    assert server.finished(bid)["stage"] == "done"
    canonical = [json.loads(line) for line in
                 (source / "recipe.jsonl").read_text(encoding="utf-8").split("\n")[1:-1]]
    kept = {op["id"]: op["path"] for op in canonical if "path" in op}
    assert "images/logo.png" in kept.values() and "brand/logo.png" in kept.values()  # canonical paths
    inputs = json.loads(seen.read_text())
    assert inputs.keys() == kept.keys()
    for op_id, (name, content) in inputs.items():
        assert client.NAME.fullmatch(name) and content == (source / kept[op_id]).read_bytes().decode("latin-1")
    sent = {kept[op_id]: name for op_id, (name, _) in inputs.items()}
    assert len(sent) == len(set(sent.values())) == 5  # one name per source, no collisions
    folder = tmp_path / "data/agent" / bid / "v1"
    assert sorted(path.name for path in folder.iterdir() if path.is_file() and path.suffix == ".png") == sorted(
        sent.values())
    assert_kept_secret([code, *tokens], capsys, caplog, tmp_path / "data")


def test_network_errors_retry_with_backoff_then_exit_nonzero(tmp_path, visitor, wrapper, fast, monkeypatch,
                                                             caplog, capsys):
    assert client.RETRY_BUDGET_S == 60
    monkeypatch.setattr(client, "RETRY_BUDGET_S", 20)
    visitor(wrapper)
    live = LiveServer(tmp_path / "server")
    probe = client.Agent(live.url, None, tmp_path / "data", [sys.executable, str(FAKE)])
    reached, result, tokens, code = {}, {}, [], None
    def call():
        with probe.http() as http:
            try:
                probe.call(http, "POST", "/claim", json={"code": "ABCD-EFGH", "agent_version": "test"})
            except client.JobError as error:  # the miss proves the retry reached the server
                reached["code"] = str(error)
    try:
        # Refused while the server is down, retried with backoff, answered once it starts.
        prober = threading.Thread(target=call, daemon=True)
        prober.start()
        wait_for(lambda: "retrying" in caplog.text, "a refused request", 15)
        live.start()
        prober.join(15)
        assert reached == {"code": "job_code_invalid"}
        tokens = record_tokens(live)
        # Mid-job the server goes away: the job's calls retry for the budget, then the engine stops.
        monkeypatch.setenv("DSS_TEST_ENGINE_TRICKLE", "1")
        alive = tmp_path / "alive"
        bid, _ = live.queue_build()
        _, code = issue(live, bid)
        with in_thread(agent_run, live, code) as (thread, result):
            wait_for(lambda: alive.exists() and "c" in alive.read_text(), "engine child")
            monkeypatch.setattr(client, "RETRY_BUDGET_S", 1)
            stopped = time.monotonic()
            live.stop()
            thread.join(30)
            assert not thread.is_alive()
            assert time.monotonic() - stopped >= 1
        size = alive.stat().st_size
        time.sleep(.5)
        assert alive.stat().st_size == size
    finally:
        live.stop()
    assert result == {"code": 1}
    out = capsys.readouterr().out
    assert "Server unavailable for 1 s" in out
    print(out)
    assert_kept_secret([code, *tokens], capsys, caplog, tmp_path / "data")


def test_backoff_doubles_and_429_or_5xx_retry_until_the_budget(tmp_path, monkeypatch):
    for name, value in (("BACKOFF_S", .05), ("BACKOFF_MAX_S", .2), ("RETRY_BUDGET_S", .6)):
        monkeypatch.setattr(client, name, value)
    agent = client.Agent("http://127.0.0.1:1", TOKEN, tmp_path, ["dsengine"])
    delays, wait = [], agent.stop.wait
    agent.stop.wait = lambda seconds: delays.append(seconds) or wait(seconds)
    def mock(handler):
        return httpx.Client(base_url=agent.server, transport=httpx.MockTransport(handler))
    codes = [429, 503, 204]
    assert agent.call(mock(lambda request: httpx.Response(codes.pop(0))), "POST", "/claim").status_code == 204
    assert delays == [.05, .1]
    delays.clear()
    with pytest.raises(client.AgentExit) as error:
        agent.call(mock(lambda request: httpx.Response(500)), "POST", "/claim")
    assert error.value.code == 1 and delays[:3] == [.05, .1, .2] and max(delays) == .2


class Clock:
    """The retry deadline's clock: backoff waits and slow attempts advance it, nothing sleeps."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return False  # stop.wait: not stopped


def scripted(tmp_path, outcomes):
    """An agent on a fake clock and a client whose attempts follow `outcomes`: (seconds, status or
    exception), with each attempt's start time, query and read timeout recorded."""
    clock, starts = Clock(), []
    agent = client.Agent("http://127.0.0.1:1", TOKEN, tmp_path, ["dsengine"])
    agent.clock, agent.stop.wait = clock, clock.advance
    def handler(request):
        starts.append((clock.now, dict(request.url.params), request.extensions["timeout"]["read"]))
        seconds, outcome = outcomes.pop(0) if outcomes else (0, 503)
        clock.advance(seconds)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)
    http = httpx.Client(base_url=agent.server, transport=httpx.MockTransport(handler),
                        timeout=httpx.Timeout(client.HTTP_TIMEOUT_S, connect=client.CONNECT_TIMEOUT_S))
    return agent, http, clock, starts


def test_transport_failures_retry_until_success_before_the_deadline(tmp_path):
    refused = httpx.ConnectError("refused")
    agent, http, clock, starts = scripted(tmp_path, [(0, refused), (0, refused), (30, refused), (0, 204)])
    assert agent.call(http, "POST", "/claim", json={}).status_code == 204
    # The first attempt has the ordinary timeout; retries are bounded by what remains.
    assert starts == [(0, {}, 40), (1, {}, 40), (3, {}, 40), (37, {}, 23)]


def test_429_and_5xx_share_the_deadline_measured_from_the_first_failure(tmp_path):
    # The first failure ends at 10 s, so the deadline is 70 s; slow attempts spend it like backoff does.
    agent, http, clock, starts = scripted(tmp_path, [(10, 429), (10, 503), (10, 502), (10, 200)])
    assert agent.call(http, "POST", "/claim", json={}).status_code == 200
    assert [start for start, *_ in starts] == [0, 11, 23, 37]
    assert [timeout for *_, timeout in starts] == [40, 40, 40, 33]
    agent, http, clock, starts = scripted(tmp_path, [(10, 429), (25, 503), (29, 500), (0, 200)])
    with pytest.raises(client.AgentExit) as error:
        agent.call(http, "POST", "/claim", json={})
    # The third attempt fails at 67 s: its 4 s backoff is cut to the 3 s left, so no fourth attempt.
    assert [start for start, *_ in starts] == [0, 11, 38] and clock.now == 70
    assert error.value.code == 1 and "Server unavailable for 60 s (HTTP 500)" in str(error.value)


def test_no_attempt_starts_at_the_deadline(tmp_path):
    agent, http, clock, starts = scripted(tmp_path, [])
    with pytest.raises(client.AgentExit):
        agent.call(http, "GET", "/jobs/r_000000000000/files/recipe.jsonl")
    # Backoff 1, 2, 4, 8 then 10 s: the last wait is cut to the 5 s left and ends exactly at 60 s.
    assert [start for start, *_ in starts] == [0, 1, 3, 7, 15, 25, 35, 45, 55] and clock.now == 60
    assert starts[-1][2] == 5


def test_retry_worker_rechecks_deadline_after_thread_scheduling(tmp_path, monkeypatch):
    agent, http, clock, starts = scripted(tmp_path, [(0, 200)])
    thread = threading.Thread
    def delayed_thread(*args, target, **kwargs):
        if kwargs.get("name") == "dss-agent-retry":
            send = target
            def target():
                clock.advance(2)
                send()
        return thread(*args, target=target, **kwargs)
    monkeypatch.setattr(client.threading, "Thread", delayed_thread)
    with pytest.raises(client.AgentExit):
        agent.attempt(http, "POST", "/claim", 1, "HTTP 503", {})
    assert starts == []
    assert agent.close_http(http).wait(1) and http.is_closed
    with pytest.raises(client.AgentExit):
        agent.call(http, "POST", "/claim")
    assert starts == []


class StalledServer:
    """A real socket server: the first request gets a 503, every later one a response whose header
    trickles in forever, so no single httpx timeout phase ever expires."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.first_failure, self.closed, self.done = None, threading.Event(), threading.Event()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        accepted = 0
        while not self.done.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            accepted += 1
            threading.Thread(target=self.answer, args=(conn, accepted == 1), daemon=True).start()

    def answer(self, conn, fail):
        with conn:
            conn.recv(65536)
            if fail:
                conn.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                self.first_failure = time.monotonic()
                return
            try:
                conn.sendall(b"HTTP/1.1 200 OK\r\n")
                while not self.done.is_set():
                    conn.sendall(b"X-Pad: a\r\n")
                    time.sleep(.1)
            except OSError:
                self.closed.set()  # the agent dropped the stalled connection

    def stop(self):
        self.done.set()
        self.sock.close()


def test_stalled_retry_cannot_outlast_the_budget_and_stops_the_engine(tmp_path, wrapper, monkeypatch, caplog,
                                                                      capfd, record_property):
    monkeypatch.setenv("DSS_TEST_ENGINE_TRICKLE", "1")
    for name, value in (("BACKOFF_S", .05), ("BACKOFF_MAX_S", .2), ("RETRY_BUDGET_S", 1.5)):
        monkeypatch.setattr(client, name, value)
    stalled, alive = StalledServer(), tmp_path / "alive"
    agent = client.Agent(stalled.url, TOKEN, tmp_path / "data", [sys.executable, str(wrapper)])
    folder = tmp_path / "data/agent" / JOB["build_id"] / "v1"
    (folder / "screens").mkdir(parents=True)
    try:
        with agent.http() as http:
            outcome = {}
            def run():
                try:
                    agent.run_engine(http, JOB["run_id"], JOB, folder)
                except client.AgentExit as error:
                    outcome.update(error=error, ended=time.monotonic())
            runner = threading.Thread(target=run, daemon=True)
            runner.start()
            runner.join(15)  # a regression fails here instead of hanging on the trickle
            assert not runner.is_alive() and "error" in outcome
            assert http.is_closed
        assert stalled.first_failure and 1.5 <= outcome["ended"] - stalled.first_failure <= 1.5 + .5
        record_property("retry_elapsed_s", outcome["ended"] - stalled.first_failure)
        assert "no answer in time" in str(outcome["error"])
        assert stalled.closed.wait(5)
        size = alive.stat().st_size
        time.sleep(.5)
        assert alive.stat().st_size == size  # engine and its child are gone
    finally:
        agent.stop.set()  # after a regression, ends the engine run that is still streaming
        stalled.stop()
    assert_no_token(caplog.text, *capfd.readouterr())


@pytest.mark.parametrize("stall", ["http_close", "process_wait", "pipe_close"])
def test_retry_expiry_bounds_stalled_cleanup(tmp_path, wrapper, monkeypatch, stall):
    """A broken close/wait cannot keep the caller or the owned engine tree alive indefinitely."""
    monkeypatch.setenv("DSS_TEST_ENGINE_TRICKLE", "1")
    for name, value in (("BACKOFF_S", .02), ("RETRY_BUDGET_S", .3)):
        monkeypatch.setattr(client, name, value)
    server, release, entered = StalledServer(), threading.Event(), threading.Event()
    agent = client.Agent(server.url, TOKEN, tmp_path, [sys.executable, str(wrapper)])
    http, processes = agent.http(), []
    start = client.start_engine
    def pause():
        entered.set()
        release.wait()  # released by finally, even on a regression
    if stall == "http_close":
        close = http.close
        def blocked_close():
            pause()
            close()
        monkeypatch.setattr(http, "close", blocked_close)
    def start_engine(*args, **kwargs):
        process = start(*args, **kwargs)
        processes.append(process)
        if stall == "process_wait":
            wait = process.wait
            def blocked_wait(*args, **kwargs):
                pause()
                return wait(*args, **kwargs)
            process.wait = blocked_wait
        if stall == "pipe_close":
            pipe = process.stdout
            class BlockedPipe:
                def __iter__(self):
                    return iter(pipe)
                def close(self):
                    pause()
                    pipe.close()
            process.stdout = BlockedPipe()
        return process
    monkeypatch.setattr(client, "start_engine", start_engine)
    outcome = {}
    def run():
        try:
            agent.run_engine(http, JOB["run_id"], JOB, tmp_path)
        except client.AgentExit as error:
            outcome.update(error=error, ended=time.monotonic())
    runner = threading.Thread(target=run, daemon=True)
    try:
        runner.start()
        runner.join(5)
        assert not runner.is_alive() and "error" in outcome
        assert entered.is_set()
        assert .3 <= outcome["ended"] - server.first_failure <= .3 + .5
        assert processes and processes[0].poll() is not None
        alive = tmp_path / "alive"
        assert "c" in alive.read_text()
        size = alive.stat().st_size
        time.sleep(.2)
        assert alive.stat().st_size == size
    finally:
        release.set()
        agent.stop.set()
        server.stop()
        runner.join(3)
        agent.close_http(http).wait(3)
    assert http.is_closed


def test_run_expiry_bounds_client_close(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(client, "RETRY_BUDGET_S", .15)
    monkeypatch.setattr(client, "BACKOFF_S", .01)
    release, close_entered = threading.Event(), threading.Event()
    agent = client.Agent("http://127.0.0.1:1", None, tmp_path, ["dsengine"])
    first, requests, closes = [], [], []
    def handler(request):
        requests.append(time.monotonic())
        if not first:
            first.append(time.monotonic())
            return httpx.Response(503)
        release.wait()
        return httpx.Response(204)
    http = httpx.Client(base_url=agent.server, transport=httpx.MockTransport(handler))
    real_close = http.close
    def close():
        closes.append(1)
        close_entered.set()
        release.wait()
        real_close()
    monkeypatch.setattr(http, "close", close)
    monkeypatch.setattr(agent, "http", lambda: http)
    outcome = {}
    def run():
        outcome.update(code=agent.run("ABCD-EFGH"), ended=time.monotonic())
    runner = threading.Thread(target=run, daemon=True)
    try:
        runner.start()
        runner.join(3)
        assert not runner.is_alive() and outcome["code"] == 1
        assert .15 <= outcome["ended"] - first[0] <= .15 + .5
        assert close_entered.is_set() and closes == [1]
        assert len(requests) == 2 and requests[-1] - first[0] < .15
    finally:
        release.set()
        runner.join(3)
        agent.close_http(http).wait(3)
    assert http.is_closed
    assert "ABCD" not in "".join(capsys.readouterr())


def claim_answer(tmp_path, monkeypatch, response):
    agent = client.Agent("http://127.0.0.1:1", None, tmp_path, [sys.executable, str(FAKE)])
    monkeypatch.setattr(agent, "http", lambda: httpx.Client(base_url=agent.server,
                                                            transport=httpx.MockTransport(lambda request: response)))
    return agent.run("ABCD-EFGH")


def error(code):
    return httpx.Response(404, json={"error": {"code": code, "message": "", "detail": {}}})


@pytest.mark.parametrize("response,code", [
    (httpx.Response(200, text="<!doctype html>"), 2), (httpx.Response(200, json={"job": {}}), 2),
    (httpx.Response(200, json={"job": {"run_id": "r_00000000000d"}, "job_token": "jt\n"}), 2),
    (httpx.Response(401), 2), (error("agent_mode_off"), 2), (error("job_not_found"), 2),
    (error("job_code_invalid"), 1), (httpx.Response(200, json={"api_version": "9.9", "token": "x"}), 2)])
def test_misconfigured_server_or_bad_claim_exits(tmp_path, monkeypatch, capsys, response, code):
    assert claim_answer(tmp_path, monkeypatch, response) == code
    out, err = capsys.readouterr()
    assert out.strip() and "ABCD" not in out + err and not (tmp_path / "agent").exists()
    # Another API version gets the update hint whatever shape its claim has.
    assert (client.UPDATE in out) is (b'"9.9"' in response.content)


def test_another_api_version_reports_failed_and_exits_2(tmp_path, monkeypatch, capsys):
    claimed, calls = {**json.loads((REPO / "contracts/fixtures/hosted-build/claimed_job.json").read_text()),
                      "api_version": "9.9"}, []
    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("x-dss-job-token"),
                      request.content and json.loads(request.content)))
        return httpx.Response(200, json=claimed if request.url.path.endswith("/claim") else {"ok": True})
    agent = client.Agent("http://127.0.0.1:1", None, tmp_path, [sys.executable, str(FAKE)])
    monkeypatch.setattr(agent, "http", lambda: httpx.Client(base_url=agent.server, transport=httpx.MockTransport(handler),
                                                            headers={"X-DSS-Job-Token": agent.token or ""}))
    assert agent.run("ABCD-EFGH") == 2
    assert calls[0][:2] == ("POST", "/api/agent/claim")
    assert calls[0][3] == {"code": "ABCD-EFGH", "agent_version": agent.version}
    run_id, token = claimed["job"]["run_id"], claimed["job_token"]
    assert calls[1][:3] == ("POST", f"/api/agent/jobs/{run_id}/finished", token) and calls[1][3]["exit_code"] == 2
    assert len(calls) == 2 and not (tmp_path / "agent").exists()
    out, err = capsys.readouterr()
    assert client.UPDATE in out and token not in out + err and "ABCD" not in out + err


def test_timeouts_engine_arguments_and_job_validation(tmp_path):
    assert (client.FLUSH_S, client.RETRY_BUDGET_S) == (1, 60)
    assert not any(hasattr(client, name) for name in ("HEARTBEAT_S", "CHECK_S", "POLL_WAIT_S"))  # no polling
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
    monkeypatch.delenv("DSS_AGENT_TOKEN", raising=False)
    monkeypatch.setenv("DSS_DATA_DIR", "")
    monkeypatch.setenv("DSS_AGENT_SERVER", "https://dss-abc123-as.a.run.app")  # 1.7: --server only
    monkeypatch.setenv("DSS_ENGINE_CMD", f'"{sys.executable}" "{FAKE}"')
    agent = client.Agent.from_env("https://dss-abc123-as.a.run.app/")
    assert agent.server == "https://dss-abc123-as.a.run.app" and agent.token is None
    assert agent.data_dir == (REPO / "data").resolve() and agent.command == [sys.executable, str(FAKE)]
    assert client.Agent.from_env("http://localhost:8000").server == "http://localhost:8000"
    monkeypatch.setenv("DSS_DATA_DIR", "../data/elsewhere")
    assert client.Agent.from_env("http://localhost:8000").data_dir == (REPO / "data/elsewhere").resolve()
    for server in (None, "", "http://example.com", "https://dss.a.run.app/builds", "https://dss.a.run.app?x=1"):
        with pytest.raises(client.AgentExit) as error:
            client.Agent.from_env(server)
        assert error.value.code == 2
    assert client.main(["run", "--server", "ftp://example.com", "--job", "ABCD-EFGH"]) == 2
    assert "ABCD" not in "".join(capsys.readouterr())


# A faked dsengine for the setup step: Chrome is up once `browser` ran (or the test says so).
CHECK_ENGINE = r'''
import json, os, sys
with open(os.environ["DSS_TEST_ENGINE_LOG"], "a") as log:
    log.write(json.dumps({"kind": sys.argv[1], "cwd": os.getcwd()}) + "\n")
up = os.environ["DSS_TEST_CHROME_UP"]
if sys.argv[1] == "browser":
    open(up, "w").close()
    sys.exit(0)
print(json.dumps({"chrome_running": os.path.exists(up), "signed_in": os.environ.get("DSS_TEST_SIGNED_IN") == "1"}))
'''


@pytest.fixture
def checker(tmp_path, monkeypatch, visitor):
    """The visitor's engine for `dss-agent check`; returns the log of its commands."""
    script = tmp_path / "check_engine.py"
    script.write_text(CHECK_ENGINE, encoding="utf-8")
    monkeypatch.setenv("DSS_TEST_ENGINE_LOG", str(tmp_path / "engine.log"))
    monkeypatch.setenv("DSS_TEST_CHROME_UP", str(tmp_path / "chrome-up"))
    monkeypatch.setenv("DSS_TEST_SIGNED_IN", "1")
    monkeypatch.setattr(client, "BROWSER_WAIT_S", .05)
    visitor(script)
    return tmp_path / "engine.log"


def new_check(server):
    response = server.api.post("/api/agent-checks")
    assert response.status_code == 201, response.text
    return response.json()


def agent_check(server, code):
    return client.main(["check", "--server", server.url, "--code", code])


def item_lines(out):
    return [line for line in out.splitlines() if line.startswith("[")]


def test_check_starts_chrome_checks_again_and_passes(server, checker, tmp_path, capsys, caplog):
    created = new_check(server)
    assert agent_check(server, created["code"]) == 0
    log = notes(checker)
    assert [entry["kind"] for entry in log] == ["check", "browser", "check"]
    assert {Path(entry["cwd"]) for entry in log} == {client.BACKEND_DIR}
    out = capsys.readouterr().out
    assert item_lines(out) == ["[ok] Server reached", "[ok] Versions match", "[ok] Chrome running", "[ok] Signed in"]
    checked = server.api.get(f"/api/agent-checks/{created['check_id']}").json()
    assert checked["state"] == "passed" and checked["result"] == {
        "agent_version": client.Agent("http://127.0.0.1:1", None, tmp_path, []).version,
        "api_version_ok": True, "chrome_running": True, "signed_in": True}
    # The code is used up: a second run says so and exits 1, Chrome already up.
    assert agent_check(server, created["code"]) == 1
    again = capsys.readouterr().out
    assert client.CHECK_CODE_INVALID in again and [entry["kind"] for entry in notes(checker)][3:] == ["check"]
    print(out + again)  # back to capsys for the secret check
    assert_kept_secret([created["code"]], capsys, caplog, tmp_path / "data")


def test_check_signed_out_exits_1_naming_login(server, checker, tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.setenv("DSS_TEST_SIGNED_IN", "0")
    (tmp_path / "chrome-up").touch()
    created = new_check(server)
    assert agent_check(server, created["code"]) == 1
    assert [entry["kind"] for entry in notes(checker)] == ["check"]  # Chrome was running: no browser
    out = capsys.readouterr().out
    lines = item_lines(out)
    assert lines[:3] == ["[ok] Server reached", "[ok] Versions match", "[ok] Chrome running"]
    assert len(lines) == 4 and lines[3].startswith("[x] Signed in") and "dsengine login" in lines[3]
    checked = server.api.get(f"/api/agent-checks/{created['check_id']}").json()
    assert checked["state"] == "failed" and checked["result"]["signed_in"] is False
    print(out)
    assert_kept_secret([created["code"]], capsys, caplog, tmp_path / "data")


def test_check_version_mismatch_exits_2(server, checker, tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.setattr(server_jobs, "API_VERSION", "9.9")  # the server's; the agent keeps its own
    created = new_check(server)
    assert agent_check(server, created["code"]) == 2
    out = capsys.readouterr().out
    lines = item_lines(out)
    assert len(lines) == 4 and lines[1].startswith("[x] Versions match") and client.UPDATE in lines[1]
    checked = server.api.get(f"/api/agent-checks/{created['check_id']}").json()
    assert checked["state"] == "failed" and checked["result"]["api_version_ok"] is False
    print(out)
    assert_kept_secret([created["code"]], capsys, caplog, tmp_path / "data")


def test_check_unreachable_server_exits_1(tmp_path, fast, monkeypatch, capsys):
    monkeypatch.setattr(client, "RETRY_BUDGET_S", .3)
    agent = client.Agent("http://127.0.0.1:1", None, tmp_path, [sys.executable, str(FAKE)])
    def refuse(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(agent, "http", lambda: httpx.Client(base_url=agent.server, transport=httpx.MockTransport(refuse)))
    assert agent.check("ABCD-EFGH") == 1
    out, err = capsys.readouterr()
    lines = item_lines(out)
    assert len(lines) == 4 and lines[0].startswith("[x] Server reached") and lines[1].startswith("[?] Versions match")
    assert lines[2:] == ["[ok] Chrome running", "[ok] Signed in"] and "ABCD" not in out + err


@pytest.mark.parametrize("response,code", [
    (httpx.Response(200, text="<!doctype html>"), 2), (error("agent_mode_off"), 2), (error("job_not_found"), 2),
    (httpx.Response(401), 2), (error("job_code_invalid"), 1)])
def test_check_misconfigured_server_exits(tmp_path, monkeypatch, capsys, response, code):
    agent = client.Agent("http://127.0.0.1:1", None, tmp_path, [sys.executable, str(FAKE)])
    monkeypatch.setattr(agent, "http", lambda: httpx.Client(base_url=agent.server,
                                                            transport=httpx.MockTransport(lambda request: response)))
    assert agent.check("ABCD-EFGH") == code
    out, err = capsys.readouterr()
    assert len(item_lines(out)) == 4 and "ready" not in out and "ABCD" not in out + err


def test_check_usage_never_echoes_the_code(server, checker, capsys):
    created = new_check(server)
    for argv in (["check", "--server", server.url], ["check", "--code", created["code"]],
                 ["check", "--server", server.url, "--code", created["code"], "--job", created["code"]]):
        assert client.main(argv) == 2
    out, err = capsys.readouterr()
    assert out.count(client.CHECK_USAGE) == 3 and created["code"] not in out + err
    assert server.api.get(f"/api/agent-checks/{created['check_id']}").json()["state"] == "waiting"
