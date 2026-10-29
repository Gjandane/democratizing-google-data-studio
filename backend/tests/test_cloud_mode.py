"""Offline cloud-mode checks: access, SPA routing and local SQLite snapshots."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import runpy
import sqlite3
import threading
import time

from fastapi.testclient import TestClient
import pytest

from dss.config import Config
from dss.db import Database
from dss.main import create_app
from fakes import fake_models

CODE = "c0de-c0de-c0de"


def cloud_app(tmp_path, **values):
    return create_app(Config(data_dir=tmp_path / "data", **values), model_lister=fake_models)


def create_build(client):
    response = client.post("/api/builds", json={"archetype": "executive", "mode": "data"})
    assert response.status_code == 201
    return response.json()["id"]


def test_access_header_cookie_rotation_and_no_secrets(tmp_path, caplog):
    app = cloud_app(tmp_path, access_code=CODE, agent_token="private-agent-token")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/session").json() == {"required": True, "ok": False,
                                                      "google_client_id": None, "user": None}
        assert client.get("/api/builds").json()["error"]["code"] == "access_required"
        assert client.get("/api/builds", headers={"X-DSS-Access-Code": CODE}).status_code == 200
        assert client.get("/api/session", headers={"X-DSS-Access-Code": CODE}).json()["ok"]
        started = time.monotonic()
        denied = client.post("/api/session", json={"code": "incorrect-秘密"})
        assert time.monotonic() - started >= 0.95
        assert denied.status_code == 401 and denied.json()["error"]["code"] == "access_denied"
        response = client.post("/api/session", json={"code": CODE})
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" not in cookie
        assert CODE not in cookie
        assert client.get("/api/session").json() == {"required": True, "ok": True,
                                                      "google_client_id": None, "user": None}
        assert client.get("/api/builds").status_code == 200
        assert CODE not in client.get("/api/settings").text
        assert "private-agent-token" not in client.get("/api/settings").text
        old_cookie = client.cookies.get("dss_session")
    with TestClient(cloud_app(tmp_path, access_code="a-different-code")) as client:
        assert client.get("/api/builds", headers={"Cookie": f"dss_session={old_cookie}"}).status_code == 401
    assert CODE not in caplog.text and "private-agent-token" not in caplog.text


@pytest.mark.parametrize("forwarded,secure", [("https", True), ("http", False)])
def test_cookie_forwarded_scheme(tmp_path, forwarded, secure):
    with TestClient(cloud_app(tmp_path, access_code=CODE)) as client:
        result = client.post("/api/session", json={"code": CODE}, headers={"X-Forwarded-Proto": forwarded})
        assert ("Secure" in result.headers["set-cookie"]) is secure
        assert result.status_code == 200


def test_https_cookie_roundtrip(tmp_path):
    with TestClient(cloud_app(tmp_path, access_code=CODE), base_url="https://host") as client:
        client.post("/api/session", json={"code": CODE})
        assert client.get("/api/builds").status_code == 200


async def test_cookie_prototype_and_sse(tmp_path):
    app = cloud_app(tmp_path, access_code=CODE)
    with TestClient(app) as client:
        client.post("/api/session", json={"code": CODE})
        build_id = create_build(client)
        folder = tmp_path / "data" / "builds" / build_id / "v1"
        folder.mkdir(parents=True, exist_ok=True)
        folder.joinpath("spec.json").write_text(Path("tests/data/thin_spec.json").read_text(), encoding="utf-8")
        assert client.get(f"/api/builds/{build_id}/prototype").status_code == 200
        sent, disconnected = [], asyncio.Event()

        async def send(message):
            sent.append(message)
            if b"event: ready" in message.get("body", b""):
                disconnected.set()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "GET", "path": f"/api/builds/{build_id}/events", "query_string": b"",
                 "headers": [(b"cookie", f"dss_session={client.cookies.get('dss_session')}".encode())],
                 "server": ("test", 80), "client": ("test", 1), "scheme": "http"}
        await asyncio.wait_for(app(scope, receive, send), 3)
        assert sent[0]["status"] == 200
        assert b"event: ready" in b"".join(item.get("body", b"") for item in sent)
        assert not app.state.bus.subscribers


def test_every_registered_api_route_is_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("DSS_DEV", "1")
    app = cloud_app(tmp_path, access_code=CODE)
    open_routes = {("GET", "/api/health"), ("GET", "/api/session"), ("POST", "/api/session")}
    with TestClient(app) as client:
        for route in app.routes:
            if not getattr(route, "path", "").startswith("/api"):
                continue
            path = route.path
            for parameter in ("build_id", "path", "name"):
                path = path.replace("{" + parameter + "}", "missing")
            for method in route.methods:
                if (method, route.path) not in open_routes:
                    response = client.request(method, path)
                    assert response.status_code == 401, (method, path)
                    assert response.json()["error"]["code"] == "access_required"
        for path in ("/api", "/api/nope", "/api/health/", "/api/session/"):
            assert client.get(path, follow_redirects=False).status_code == 401
        assert client.delete("/api/session").status_code == 401
        # The future agent router has a separate token gate, never a session gate.
        assert client.get("/api/agent/jobs/next").status_code == 404
        assert client.get("/api/agentish").status_code == 401


def test_no_code_preserves_local_access(tmp_path):
    with TestClient(cloud_app(tmp_path)) as client:
        local = {"required": False, "ok": True, "google_client_id": None, "user": None}
        assert client.get("/api/session").json() == local
        assert client.get("/api/builds").status_code == 200
        assert client.post("/api/session", json={"code": ""}).json() == local
        assert client.get("/api/nope").status_code == 404


@pytest.mark.parametrize("code,mode,token,error", [
    ("", "local", "", "DSS_ACCESS_CODE"),
    ("x" * 11, "local", "", "DSS_ACCESS_CODE"),
    ("x" * 12, "agent", "", "DSS_AGENT_TOKEN"),
    ("x" * 12, "agent", "t" * 23, "DSS_AGENT_TOKEN"),
])
def test_fail_closed(tmp_path, code, mode, token, error):
    app = cloud_app(tmp_path, cloud_service="dss", access_code=code, engine_mode=mode, agent_token=token)
    with pytest.raises(RuntimeError, match=error):
        with TestClient(app):
            pass
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("cloud", ["", "dss"])
def test_google_signin_needs_access_code(tmp_path, cloud):
    app = cloud_app(tmp_path, cloud_service=cloud, google_client_id="1-x.apps.googleusercontent.com")
    with pytest.raises(RuntimeError, match="GOOGLE_OAUTH_CLIENT_ID requires DSS_ACCESS_CODE"):
        with TestClient(app):
            pass
    assert not (tmp_path / "data").exists()


def test_open_link_starts_ungated_and_warns_once(tmp_path, caplog):
    app = cloud_app(tmp_path, cloud_service="dss", public_link="1", db_path=tmp_path / "local.sqlite")
    with caplog.at_level("WARNING", logger="dss.main"):
        with TestClient(app) as client:
            assert client.get("/api/session").json() == {"required": False, "ok": True,
                                                         "google_client_id": None, "user": None}
            assert client.get("/api/builds").status_code == 200
    warnings = [r for r in caplog.records if r.name == "dss.main" and "API is open" in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelname == "WARNING"


@pytest.mark.parametrize("public,code,client_id,error", [
    ("1", CODE, "", "DSS_PUBLIC=1 requires"),
    ("1", "", "1-x.apps.googleusercontent.com", "DSS_PUBLIC=1 requires"),
    ("yes", "", "", "DSS_PUBLIC must be 1"),
    ("", "", "", "DSS_ACCESS_CODE of at least 12"),
])
def test_open_link_fail_closed(tmp_path, public, code, client_id, error):
    app = cloud_app(tmp_path, cloud_service="dss", public_link=public, access_code=code,
                    google_client_id=client_id, db_path=tmp_path / "local.sqlite")
    with pytest.raises(RuntimeError, match=error):
        with TestClient(app):
            pass
    assert not (tmp_path / "data").exists()


def test_open_link_ignored_off_cloud_run(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="dss.main"):
        with TestClient(cloud_app(tmp_path, public_link="1", access_code=CODE)) as client:
            assert client.get("/api/session").json()["required"] is True
            assert client.get("/api/builds").status_code == 401
    assert "API is open" not in caplog.text


def test_valid_cloud_start_and_local_sqlite_required(tmp_path):
    config = dict(cloud_service="dss", access_code="x" * 12, engine_mode="agent", agent_token="t" * 24)
    with TestClient(cloud_app(tmp_path, db_path=tmp_path / "local.sqlite", **config)) as client:
        assert client.get("/api/health").status_code == 200
    with pytest.raises(RuntimeError, match="DSS_DB_PATH outside DSS_DATA_DIR"):
        with TestClient(cloud_app(tmp_path, db_path=tmp_path / "data" / "unsafe.sqlite", **config)):
            pass


def test_spa_and_api_404(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>dashboard app</html>")
    (static / "assets" / "a.js").write_text("console.log('app')")
    with TestClient(cloud_app(tmp_path, static_dir=static)) as client:
        for path in ("/", "/builds/b_123", "/missing.css"):
            assert client.get(path).text == "<html>dashboard app</html>"
        assert client.get("/assets/a.js").text == "console.log('app')"
        for path in ("/api/nope", "/api", "/api/nope/"):
            response = client.get(path)
            assert response.status_code == 404
            assert response.json() == {"error": {"code": "not_found", "message": "Request could not be handled", "detail": {}}}


def test_module_server_options(tmp_path, monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setenv("PORT", "8187")
    monkeypatch.setattr(Config, "from_env", classmethod(lambda cls: Config(data_dir=tmp_path)))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    runpy.run_path("src/dss/main.py", run_name="__main__")
    assert calls == [{"host": "0.0.0.0", "port": 8187, "forwarded_allow_ips": "*", "timeout_graceful_shutdown": 3}]


def test_env_config(tmp_path, monkeypatch):
    import dss.config as config_module
    monkeypatch.setattr(config_module, "dotenv_values", lambda path: {})
    values = {"DSS_ACCESS_CODE": CODE, "DSS_AGENT_TOKEN": "t" * 24, "DSS_ENGINE_MODE": "agent",
              "DSS_DATA_DIR": str(tmp_path / "data"), "DSS_DB_PATH": str(tmp_path / "local.sqlite"),
              "DSS_STATIC_DIR": str(tmp_path / "static"), "K_SERVICE": "dss",
              "GOOGLE_OAUTH_CLIENT_ID": " 1-x.apps.googleusercontent.com ",
              "DSS_SIGNIN_ALLOW": " @Example.com, ,Judge@Example.com,* ", "DSS_PUBLIC": "1"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    config = Config.from_env()
    assert config.access_code.get_secret_value() == CODE
    assert config.agent_token.get_secret_value() == "t" * 24
    assert config.engine_mode == "agent" and config.cloud_service == "dss"
    assert config.db_path == tmp_path / "local.sqlite" and config.static_dir == tmp_path / "static"
    assert config.google_client_id == "1-x.apps.googleusercontent.com"
    assert config.signin_allow == ("@example.com", "judge@example.com", "*")
    assert config.public_link == "1" and config.open_link
    assert CODE not in repr(config) and CODE not in json.dumps(config.public())


def test_shutdown_restore(tmp_path):
    local = tmp_path / "local" / "dss.sqlite"
    app = cloud_app(tmp_path, db_path=local)
    with TestClient(app) as client:
        build_id = create_build(client)
        assert not (tmp_path / "data" / "dss.sqlite").exists()
    assert (tmp_path / "data" / "dss.sqlite").is_file()
    local.unlink()
    with TestClient(cloud_app(tmp_path, db_path=local)) as client:
        assert client.get("/api/builds").json()[0]["id"] == build_id


def test_periodic_only_when_dirty_and_no_volume_connections(tmp_path, monkeypatch):
    import dss.db as db_module
    monkeypatch.setattr(db_module, "BACKUP_INTERVAL_S", 0.03)
    original_connect, original_backup = sqlite3.connect, Database.backup
    opened, backups = [], []

    def connect(path, *args, **kwargs):
        opened.append(Path(path).resolve())
        return original_connect(path, *args, **kwargs)

    def backup(db, **kwargs):
        original_backup(db, **kwargs)
        if db.backup_path.exists():
            backups.append(db.backup_path.stat().st_mtime_ns)

    monkeypatch.setattr(db_module.sqlite3, "connect", connect)
    monkeypatch.setattr(Database, "backup", backup)
    app = cloud_app(tmp_path, db_path=tmp_path / "local.sqlite")
    with TestClient(app) as client:
        deadline = time.monotonic() + 3
        while app.state.db.dirty and time.monotonic() < deadline:
            time.sleep(0.01)
        assert backups and not app.state.db.dirty
        before = (tmp_path / "data" / "dss.sqlite").stat().st_mtime_ns
        for _ in range(5):
            assert client.get("/api/builds").status_code == 200
            time.sleep(0.02)
        assert (tmp_path / "data" / "dss.sqlite").stat().st_mtime_ns == before
        create_build(client)
        deadline = time.monotonic() + 3
        while app.state.db.dirty and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not app.state.db.dirty
        assert (tmp_path / "data" / "dss.sqlite").stat().st_mtime_ns != before
    assert all(not path.is_relative_to(tmp_path / "data") for path in opened)


def test_backup_failure_retries_without_breaking_requests(tmp_path, monkeypatch, caplog):
    import dss.db as db_module
    app = cloud_app(tmp_path, db_path=tmp_path / "local.sqlite")
    with TestClient(app) as client:
        create_build(client)
        with monkeypatch.context() as patch:
            def fail(*args):
                raise OSError("sensitive-deployment-path")
            patch.setattr(db_module.shutil, "copyfile", fail)
            app.state.db.backup()
            assert app.state.db.dirty
            assert client.get("/api/builds").status_code == 200
        app.state.db.backup()
        assert not app.state.db.dirty
    assert "Database backup failed" in caplog.text and "sensitive-deployment-path" not in caplog.text


def test_backup_serialization_and_write_during_snapshot(tmp_path, monkeypatch):
    import dss.db as db_module
    db = Database(tmp_path / "local.sqlite", tmp_path / "data")
    db.initialize()
    entered, release = threading.Event(), threading.Event()
    original_copy = db_module.shutil.copyfile
    active, maximum = 0, 0
    lock = threading.Lock()

    def copy(*args):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(active, maximum)
        entered.set()
        assert release.wait(3)
        try:
            return original_copy(*args)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(db_module.shutil, "copyfile", copy)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(db.backup)
        assert entered.wait(3)
        with db.connect() as conn:
            conn.execute("INSERT INTO settings VALUES('worker_model','new')")
        release.set()
        first.result(timeout=3)
        assert db.dirty  # A commit after the snapshot must survive for the next backup.
        left, right = pool.submit(db.backup), pool.submit(db.backup)
        left.result(timeout=3)
        right.result(timeout=3)
    assert maximum == 1 and not db.dirty
    restored = Database(tmp_path / "restored.sqlite", tmp_path / "data")
    restored.initialize()
    with restored.connect() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='worker_model'").fetchone()[0] == "new"


def test_rollback_does_not_dirty_database(tmp_path):
    db = Database(tmp_path / "local.sqlite", tmp_path / "data")
    db.initialize()
    db.backup()
    with pytest.raises(ValueError):
        with db.connect() as conn:
            conn.execute("INSERT INTO settings VALUES('worker_model','discard')")
            raise ValueError("rollback")
    assert not db.dirty


@pytest.mark.parametrize("periodic", [False, True])
def test_stalled_backup_does_not_hold_shutdown(tmp_path, monkeypatch, caplog, periodic):
    import dss.db as db_module
    import dss.main as main_module
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    workers = []
    original = Database.backup

    def stalled(db, **kwargs):
        workers.append(threading.current_thread())
        entered.set()
        try:
            assert release.wait(3)
            return original(db, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(main_module, "SHUTDOWN_BACKUP_TIMEOUT_S", 0.05)
    monkeypatch.setattr(db_module, "BACKUP_INTERVAL_S", 0.01 if periodic else 30)
    monkeypatch.setattr(Database, "backup", stalled)
    try:
        with TestClient(cloud_app(tmp_path, db_path=tmp_path / "local.sqlite")) as client:
            create_build(client)
            if periodic:
                assert entered.wait(3)
            started = time.monotonic()
        assert time.monotonic() - started < 1
        assert entered.is_set() and not finished.is_set()
        assert all(worker.daemon for worker in workers)
        assert "Database backup exceeded the shutdown budget" in caplog.text
    finally:
        release.set()
        assert finished.wait(3)
