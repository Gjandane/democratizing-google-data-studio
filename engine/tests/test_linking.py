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
# Recipe 1.5: without a template, Data Studio's default report takes only un-aliased ds.* params.
BARE_SUFFIX = ("&ds.connector=bigQuery&ds.type=TABLE&ds.projectId=source-project"
               "&ds.datasetId=demo&ds.tableId=orders&ds.billingProjectId=billing-project")


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
    assert build_url(header, project_id="billing-project", template_id="") == PREFIX + encoded + BARE_SUFFIX
    assert build_url(header, project_id="billing-project", template_id="tpl") == (
        PREFIX + encoded + SUFFIX + "&c.reportId=tpl")


def test_no_template_env_drops_alias(header, monkeypatch):
    monkeypatch.delenv("DSS_TEMPLATE_REPORT_ID", raising=False)
    monkeypatch.setenv("GCP_PROJECT_ID", "billing-project")
    header.report_name = "Revenue"
    url = build_url(header)
    assert url == PREFIX + "Revenue" + BARE_SUFFIX
    assert "ds.ds0" not in url and "c.reportId" not in url


def test_template_env_and_all_values_are_encoded(header, monkeypatch):
    header.report_name = "Revenue"
    monkeypatch.setenv("GCP_PROJECT_ID", "billing-project")
    monkeypatch.setenv("DSS_TEMPLATE_REPORT_ID", "template /&東京")
    assert build_url(header) == PREFIX + "Revenue" + SUFFIX + "&c.reportId=template%20%2F%26%E6%9D%B1%E4%BA%AC"
    header.datasource.project_id = "a&b"
    header.datasource.dataset_id = "a#b"
    header.datasource.table_id = "a b"
    assert build_url(header, project_id="bill/東京", template_id="") == (
        PREFIX + "Revenue&ds.connector=bigQuery&ds.type=TABLE"
        "&ds.projectId=a%26b&ds.datasetId=a%23b&ds.tableId=a%20b"
        "&ds.billingProjectId=bill%2F%E6%9D%B1%E4%BA%AC")


@pytest.mark.parametrize("template", [None, "", "tpl"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_billing_project_fails_without_browser_work(header, monkeypatch, value, template):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("DSS_TEMPLATE_REPORT_ID", raising=False)
    monkeypatch.setattr(chrome, "ensure_browser", lambda *a: pytest.fail("browser touched"))
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        build_url(header, project_id=value, template_id=template)


def test_explicit_empty_template_overrides_env(header, monkeypatch):
    monkeypatch.setenv("DSS_TEMPLATE_REPORT_ID", "template")
    header.report_name = "Revenue"
    assert build_url(header, project_id="billing-project", template_id="") == PREFIX + "Revenue" + BARE_SUFFIX


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


GCS_SAMPLE = SAMPLE.with_name("recipe.gcs.sample.jsonl")
GCS_URL = (PREFIX + "Revenue&ds.ds0.connector=googleCloudStorage&ds.ds0.pathType=FILE"
           "&ds.ds0.path=my-bucket%2Fshare%20dir%2F%E6%9D%B1%2Fdata.csv")
GCS_BARE_URL = (PREFIX + "Revenue&ds.connector=googleCloudStorage&ds.pathType=FILE"
                "&ds.path=my-bucket%2Fshare%20dir%2F%E6%9D%B1%2Fdata.csv")


@pytest.fixture
def gcs_header():
    value = load_recipe(GCS_SAMPLE).header.model_copy(deep=True)
    value.report_name = "Revenue"
    value.datasource.path = "my-bucket/share dir/東/data.csv"
    return value


@pytest.mark.parametrize("template", [None, ""])
@pytest.mark.parametrize("billing", [None, "", "billing-project"])
def test_gcs_url_never_reads_billing_project(gcs_header, monkeypatch, billing, template):
    # Recipe 1.4: a visitor's machine has no GCP_PROJECT_ID; it is never added.
    # Recipe 1.5: nor a template, so the source params carry no ds0 alias.
    monkeypatch.setenv("GCP_PROJECT_ID", "env-billing")
    monkeypatch.delenv("DSS_TEMPLATE_REPORT_ID", raising=False)
    url = build_url(gcs_header, project_id=billing, template_id=template)
    assert url == GCS_BARE_URL
    assert "ds.ds0" not in url and "c.reportId" not in url


def test_gcs_url_with_template_argument_keeps_alias(gcs_header, monkeypatch):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("DSS_TEMPLATE_REPORT_ID", raising=False)
    assert build_url(gcs_header, template_id="tpl") == GCS_URL + "&c.reportId=tpl"


def test_gcs_url_appends_template_last(gcs_header, monkeypatch):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.setenv("DSS_TEMPLATE_REPORT_ID", "template /&")
    assert build_url(gcs_header) == GCS_URL + "&c.reportId=template%20%2F%26"


def _default_page(remaining):
    # Fake editor: `remaining` components until Delete removes them all.
    keys = []
    components = SimpleNamespace(count=lambda: remaining[0])

    def press(key):
        keys.append(key)
        if key == "Delete":
            remaining[0] = 0

    page = SimpleNamespace(keyboard=SimpleNamespace(press=press), wait_for_timeout=lambda ms: None)
    ctx = SimpleNamespace(locator=lambda p, key: components, op_deadline=float("inf"),
                          remaining_s=lambda: 10.0)
    return page, ctx, keys


@pytest.mark.parametrize(("template", "default"), [("", True), ("tpl", False)])
def test_default_report_detected_only_without_template(header, template, default):
    from dsengine.ops import report
    ctx = SimpleNamespace(open_url=build_url(header, project_id="billing-project", template_id=template))
    assert report._default_report(ctx) is default


def test_open_report_deletes_default_components(monkeypatch):
    from dsengine.ops import OperationError, report
    clicks = []
    monkeypatch.setattr(report, "_click_workspace", lambda page, ctx, canvas: clicks.append(canvas))
    remaining = [3]
    page, ctx, keys = _default_page(remaining)
    assert report._clear_default_components(page, ctx, "canvas") == 3
    assert (clicks, keys, remaining) == (["canvas"], ["ControlOrMeta+a", "Delete"], [0])
    ctx.open_url = "https://datastudio.google.com/reporting/create?ds.connector=bigQuery"
    page.url = "https://datastudio.google.com/reporting/abc/edit"
    monkeypatch.setattr(report, "_visible", lambda locator: True)
    report.verify(page, SimpleNamespace(op="open_report"), ctx)
    remaining[0] = 1
    with pytest.raises(OperationError, match="default report still holds components"):
        report.verify(page, SimpleNamespace(op="open_report"), ctx)
