"""Exact Linking API oracle and offline coverage for safe Chrome ownership."""

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsengine import chrome
from dsengine.cli import main
from dsengine.linking import build_url
from dsengine.recipe import load_recipe

SAMPLE = Path(__file__).resolve().parents[2] / "contracts/fixtures/recipe.sample.jsonl"
PREFIX = "https://datastudio.google.com/reporting/create?c.mode=edit&r.reportName="
SUFFIX = ("&ds.ds0.connector=bigQuery&ds.ds0.type=TABLE"
          "&ds.ds0.projectId=source-project&ds.ds0.datasetId=demo"
          "&ds.ds0.tableId=orders&ds.ds0.billingProjectId=billing-project")


@pytest.fixture
def header():
    value = load_recipe(SAMPLE).header.model_copy(deep=True)
    value.datasource.project_id = "source-project"
    value.datasource.dataset_id = "demo"
    value.datasource.table_id = "orders"
    return value


@pytest.mark.parametrize(("name", "encoded"), [
    ("Revenue", "Revenue"), ("A & B #1", "A%20%26%20B%20%231"),
    ("Café 東京", "Caf%C3%A9%20%E6%9D%B1%E4%BA%AC"),
    ("a+b/c?d=e%", "a%2Bb%2Fc%3Fd%3De%25"),
])
def test_exact_url(header, name, encoded):
    header.report_name = name
    assert build_url(header, project_id="billing-project", template_id="") == PREFIX + encoded + SUFFIX


def test_template_env_and_all_values_are_encoded(header, monkeypatch):
    header.report_name = "Revenue"
    monkeypatch.setenv("GCP_PROJECT_ID", "billing-project")
    monkeypatch.setenv("DSS_TEMPLATE_REPORT_ID", "template /&東京")
    assert build_url(header) == PREFIX + "Revenue" + SUFFIX + "&c.reportId=template%20%2F%26%E6%9D%B1%E4%BA%AC"
    header.datasource.project_id = "a&b"
    header.datasource.dataset_id = "a#b"
    header.datasource.table_id = "a b"
    assert build_url(header, project_id="bill/東京", template_id="") == (
        PREFIX + "Revenue&ds.ds0.connector=bigQuery&ds.ds0.type=TABLE"
        "&ds.ds0.projectId=a%26b&ds.ds0.datasetId=a%23b&ds.ds0.tableId=a%20b"
        "&ds.ds0.billingProjectId=bill%2F%E6%9D%B1%E4%BA%AC")


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_billing_project_fails_without_browser_work(header, monkeypatch, value):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.setattr(chrome, "ensure_browser", lambda *a: pytest.fail("browser touched"))
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        build_url(header, project_id=value)


def test_explicit_empty_template_overrides_env(header, monkeypatch):
    monkeypatch.setenv("DSS_TEMPLATE_REPORT_ID", "template")
    header.report_name = "Revenue"
    assert build_url(header, project_id="billing-project", template_id="") == PREFIX + "Revenue" + SUFFIX


@pytest.fixture
def config(tmp_path):
    return chrome.ChromeConfig(tmp_path / "profile", 9222)


def test_config_defaults_are_engine_relative(monkeypatch):
    monkeypatch.delenv("DSS_CHROME_PROFILE", raising=False)
    monkeypatch.delenv("DSS_CDP_PORT", raising=False)
    assert chrome.ChromeConfig.from_env() == chrome.ChromeConfig(
        (chrome.ENGINE_ROOT.parent / ".chrome-profile").resolve(), 9222)


@pytest.mark.parametrize("port", ["0", "65536", "bad", "9222.5"])
def test_bad_port_is_safe_error(monkeypatch, port):
    monkeypatch.setenv("DSS_CDP_PORT", port)
    with pytest.raises(chrome.ChromeError, match="DSS_CDP_PORT"):
        chrome.ChromeConfig.from_env()


def test_missing_chrome_names_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("DSS_CHROME_PATH", str(tmp_path / "missing-secret-path"))
    with pytest.raises(chrome.ChromeError, match="DSS_CHROME_PATH") as error:
        chrome.chrome_path()
    assert "missing-secret-path" not in str(error.value)


def register(config, websocket="ws://127.0.0.1:9222/devtools/browser/owned"):
    config.profile.mkdir(exist_ok=True)
    config.marker.write_text(json.dumps({"websocket": websocket, "port": config.port}))
    return {"webSocketDebuggerUrl": websocket}


def test_browser_running_is_noop_only_for_owned_endpoint(config, monkeypatch):
    version = register(config)
    monkeypatch.setattr(chrome, "_version", lambda c: version)
    monkeypatch.setattr(chrome.subprocess, "Popen", lambda *a, **kw: pytest.fail("launched twice"))
    assert chrome.ensure_browser(config) == version["webSocketDebuggerUrl"]
    config.marker.write_text("{}")
    with pytest.raises(chrome.ChromeError, match="unrecognized"):
        chrome.ensure_browser(config)


def test_stale_marker_refuses_another_browser(config, monkeypatch):
    register(config)
    monkeypatch.setattr(chrome, "_version", lambda c: {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/other"})
    with pytest.raises(chrome.ChromeError, match="unrecognized"):
        chrome.ensure_browser(config)


@pytest.mark.parametrize("websocket", [None, 42, "ws://127.0.0.1:bad/path", "ws://remote:9222/path"])
def test_malformed_endpoint_is_safe_error(config, websocket):
    register(config)
    config.marker.write_text("[]")
    with pytest.raises(chrome.ChromeError, match="unrecognized"):
        chrome._owned_endpoint(config, {"webSocketDebuggerUrl": websocket})


def test_busy_non_cdp_port_refused(config, monkeypatch):
    monkeypatch.setattr(chrome, "_version", lambda c: None)
    monkeypatch.setattr(chrome, "_port_busy", lambda c: True)
    for action in (chrome.ensure_browser, chrome.check):
        with pytest.raises(chrome.ChromeError, match="busy"):
            action(config)


def test_browser_launch_flags_and_marker(config, monkeypatch):
    version = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/new"}
    versions = iter([None, version])
    monkeypatch.setattr(chrome, "_version", lambda c: next(versions))
    monkeypatch.setattr(chrome, "_port_busy", lambda c: False)
    monkeypatch.setattr(chrome, "chrome_path", lambda: "chrome.exe")
    calls = []
    monkeypatch.setattr(chrome.subprocess, "Popen", lambda args, **kw: calls.append(args))
    assert chrome.ensure_browser(config, chrome.ACCOUNTS_URL) == version["webSocketDebuggerUrl"]
    assert calls == [["chrome.exe", f"--user-data-dir={config.profile}",
                      "--remote-debugging-port=9222", "--remote-debugging-address=127.0.0.1",
                      "--no-first-run", "--no-default-browser-check", "--app=https://accounts.google.com/"]]
    assert "owned" not in config.marker.read_text()


def test_cli_check_stopped_does_not_launch(config, monkeypatch, capsys):
    monkeypatch.setattr(chrome.ChromeConfig, "from_env", lambda: config)
    monkeypatch.setattr(chrome, "_version", lambda c: None)
    monkeypatch.setattr(chrome, "_port_busy", lambda c: False)
    monkeypatch.setattr(chrome, "ensure_browser", lambda *a: pytest.fail("launched"))
    assert main(["check"]) == 0
    assert json.loads(capsys.readouterr().out) == {"chrome_running": False, "signed_in": False}


@pytest.mark.parametrize("signed_in", [False, True])
def test_check_uses_and_closes_only_new_page(config, monkeypatch, signed_in):
    closed = []
    page = SimpleNamespace(close=lambda: closed.append(True))
    context = SimpleNamespace(new_page=lambda: page)

    @contextmanager
    def attached(c):
        yield context

    monkeypatch.setattr(chrome, "attached", attached)
    monkeypatch.setattr(chrome, "_version", lambda c: {"running": True})
    monkeypatch.setattr(chrome, "_studio_signed_in", lambda p, c: signed_in)
    assert chrome.check(config) == {"chrome_running": True, "signed_in": signed_in}
    assert closed == [True]


def test_cli_chrome_error_is_event_and_stderr(monkeypatch, capsys):
    def fail():
        raise chrome.ChromeError("DSS_CDP_PORT is busy; use a free port")
    monkeypatch.setattr(chrome.ChromeConfig, "from_env", fail)
    assert main(["browser"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["event"] == "log"
    assert "DSS_CDP_PORT" in output.err
