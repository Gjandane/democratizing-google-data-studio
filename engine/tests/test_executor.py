import io
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

import dsengine.executor as executor
from dsengine.chrome import ChromeConfig, ensure_browser
from dsengine.events import EventWriter
from dsengine.ops import OpContext, OpResult
from dsengine.recipe import Canvas, Datasource, Header, Operation, Recipe


class FakeKeyboard:
    def __init__(self, calls):
        self.calls = calls

    def press(self, key, *, delay=None):
        self.calls.append(("press", key))


class FakeMouse:
    def __init__(self, calls):
        self.calls = calls

    def click(self, x, y, *, button=None, click_count=None, delay=None):
        self.calls.append(("click", x, y))


class FakeCanvas:
    def count(self):
        return 1

    def is_visible(self):
        return True

    def bounding_box(self, *, timeout=None):
        return {"x": 200, "y": 100, "width": 1200, "height": 900}


class FakePage:
    def __init__(self, calls):
        self.keyboard = FakeKeyboard(calls)
        self.mouse = FakeMouse(calls)
        self.canvas = FakeCanvas()
        self.closed = False

    def locator(self, selector):
        assert selector == "fake"
        return self.canvas

    def set_viewport_size(self, _size):
        pass

    def set_default_timeout(self, _timeout):
        pass

    def screenshot(self, *, path, **_kwargs):
        Path(path).write_bytes(b"fake screenshot")

    def close(self):
        self.closed = True


class FakeBrowserContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


class FakeHandler:
    def __init__(self, calls, fail_run=None, fail_verify=None):
        self.calls = calls
        self.fail_run = fail_run or {}
        self.fail_verify = fail_verify or {}

    def run(self, _page, op, _ctx):
        self.calls.append(("run", op.op, op.id))
        left = self.fail_run.get(op.id, 0)
        if left:
            self.fail_run[op.id] = left - 1
            raise RuntimeError("failure from fake driver")
        return OpResult()

    def verify(self, _page, op, ctx):
        self.calls.append(("verify", op.op, op.id))
        left = self.fail_verify.get(op.id, 0)
        if left:
            self.fail_verify[op.id] = left - 1
            raise RuntimeError("verification failure from fake driver")
        if op.op == "get_link":
            ctx.report_url = "https://datastudio.google.com/reporting/fake/page/fake"


def make_recipe(tmp_path, *names):
    header = Header(
        recipe_version="1.0",
        build_id="b_123456789abc",
        version=1,
        report_name="executor test",
        canvas=Canvas(width=1200, height=900),
        datasource=Datasource(connector="bigQuery", project_id="project",
                              dataset_id="dataset", table_id="table"),
    )
    ops = [Operation(id=f"s{index:03d}", op=name)
           for index, name in enumerate(names, 1)]
    return Recipe(path=tmp_path / "recipe.jsonl", header=header, ops=ops)


@pytest.fixture
def fake_driver(monkeypatch, tmp_path):
    calls = []
    page = FakePage(calls)
    monkeypatch.setattr(executor, "load_selectors", lambda: {"canvas": "fake"})
    monkeypatch.setattr(executor, "build_url", lambda _header: "https://datastudio.google.com/reporting/create?test=1")
    monkeypatch.setattr(executor.chrome, "check", lambda _config: {"signed_in": True})
    monkeypatch.setattr(executor.chrome, "ensure_browser", lambda _config: None)
    config = ChromeConfig(tmp_path / "profile", 9222)
    monkeypatch.setattr(executor.chrome.ChromeConfig, "from_env", lambda: config)

    @contextmanager
    def attach(_config):
        yield FakeBrowserContext(page)

    monkeypatch.setattr(executor.chrome, "attached", attach)
    stream = io.StringIO()
    return page, calls, EventWriter(stream), stream


def read_events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def install_handler(monkeypatch, calls, **kwargs):
    handler = FakeHandler(calls, **kwargs)
    monkeypatch.setattr(executor, "handler_for", lambda _name: handler)
    return handler


def test_ops_run_in_order_with_one_start_finish_pair_each(fake_driver, monkeypatch, tmp_path):
    page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls)
    recipe = make_recipe(tmp_path, "open_report", "set_canvas", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 0

    records = read_events(stream)
    op_events = [event for event in records if event["event"].startswith("op_")]
    assert [(event["event"], event["op_id"]) for event in op_events] == [
        ("op_started", "s001"), ("op_finished", "s001"),
        ("op_started", "s002"), ("op_finished", "s002"),
        ("op_started", "s003"), ("op_finished", "s003"),
        ("op_started", "s004"), ("op_finished", "s004"),
    ]
    assert calls == [
        ("run", "open_report", "s001"), ("verify", "open_report", "s001"),
        ("run", "set_canvas", "s002"), ("verify", "set_canvas", "s002"),
        ("run", "save_report", "s003"), ("verify", "save_report", "s003"),
        ("run", "get_link", "s004"), ("verify", "get_link", "s004"),
    ]
    assert records[-1]["status"] == "ok"
    assert records[-1]["report_url"].endswith("/page/fake")
    assert page.closed


def test_retries_once_screenshots_and_continues(fake_driver, monkeypatch, tmp_path):
    page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls, fail_verify={"s002": 2})
    recipe = make_recipe(tmp_path, "open_report", "set_canvas", "save_report", "get_link")
    screens = tmp_path / "screens"

    assert executor.run_recipe(recipe, events, screens=screens) == 0

    records = read_events(stream)
    failed = next(event for event in records if event.get("op_id") == "s002"
                  and event["event"] == "op_finished")
    assert failed["status"] == "failed"
    assert failed["screenshot"] == "s002_failed.png"
    assert (screens / "s002_failed.png").is_file()
    assert calls.count(("verify", "set_canvas", "s002")) == 2
    assert calls.count(("press", "Escape")) == 1
    assert calls.count(("click", 188, 140)) == 1
    assert ("run", "save_report", "s003") in calls
    assert ("run", "get_link", "s004") in calls
    assert records[-1]["status"] == "partial"
    assert records[-1]["failed"] == 1


def test_open_report_failure_aborts_with_exit_one(fake_driver, monkeypatch, tmp_path):
    _page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls, fail_run={"s001": 2})
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 1

    records = read_events(stream)
    assert [event["event"] for event in records] == [
        "run_started", "op_started", "op_finished", "run_finished"
    ]
    assert records[-1]["status"] == "failed"
    assert records[-1]["error_code"] == "open_report_failed"
    assert not any(call[1] in {"save_report", "get_link"} for call in calls if len(call) > 1)


@pytest.mark.parametrize("failure", ["fail_run", "fail_verify"])
def test_cleanup_runs_before_second_attempt(fake_driver, monkeypatch, tmp_path, failure):
    _page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls, **{failure: {"s002": 1}})
    recipe = make_recipe(tmp_path, "open_report", "set_canvas", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 0

    failed_call = ("run" if failure == "fail_run" else "verify", "set_canvas", "s002")
    first_attempt = calls.index(failed_call)
    assert calls[first_attempt:first_attempt + 4] == [
        failed_call, ("press", "Escape"), ("click", 188, 140),
        ("run", "set_canvas", "s002"),
    ]
    assert read_events(stream)[-1]["status"] == "ok"


def cleanup_context(tmp_path):
    return OpContext(
        recipe=make_recipe(tmp_path), selectors={"canvas": "fake"},
        events=EventWriter(io.StringIO()), screens=tmp_path / "screens",
        run_deadline=120, op_deadline=110,
    )


@pytest.mark.parametrize("unavailable", [
    "page", "closed_page", "missing_selector", "missing_canvas", "hidden_canvas", "no_box",
])
def test_cleanup_is_safe_when_page_or_canvas_unavailable(monkeypatch, tmp_path, unavailable):
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    calls = []
    page = FakePage(calls)
    ctx = cleanup_context(tmp_path)
    if unavailable == "page":
        page = None
    elif unavailable == "closed_page":
        def closed(*_args, **_kwargs):
            raise RuntimeError("page closed")
        monkeypatch.setattr(page.keyboard, "press", closed)
        monkeypatch.setattr(page, "locator", closed)
    elif unavailable == "missing_selector":
        ctx.selectors = {}
    elif unavailable == "missing_canvas":
        monkeypatch.setattr(page.canvas, "count", lambda: 0)
    elif unavailable == "hidden_canvas":
        monkeypatch.setattr(page.canvas, "is_visible", lambda: False)
    else:
        monkeypatch.setattr(page.canvas, "bounding_box", lambda *, timeout=None: None)

    executor.reset_ui(page, ctx)

    assert calls == ([] if unavailable in {"page", "closed_page"} else [("press", "Escape")])


def test_cleanup_still_deselects_if_escape_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    calls = []
    page = FakePage(calls)

    def fail_press(key, *, delay=None):
        raise RuntimeError("keyboard unavailable")

    monkeypatch.setattr(page.keyboard, "press", fail_press)
    executor.reset_ui(page, cleanup_context(tmp_path))

    assert calls == [("click", 188, 140)]


@pytest.mark.parametrize("run_deadline, op_deadline, bypass, remaining_ms", [
    (120, 110, False, 10000), (105, 110, False, 5000),
    (99, 110, True, 10000), (120, 99, False, 0), (99, 110, False, 0),
])
def test_cleanup_uses_existing_budget(
    monkeypatch, tmp_path, run_deadline, op_deadline, bypass, remaining_ms,
):
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    calls = []
    page = FakePage(calls)
    ctx = cleanup_context(tmp_path)
    ctx.run_deadline, ctx.op_deadline = run_deadline, op_deadline
    ctx.bypass_run_deadline = bypass
    timeouts = []

    def bounding_box(*, timeout=None):
        timeouts.append(timeout)
        return FakeCanvas().bounding_box()

    monkeypatch.setattr(page.canvas, "bounding_box", bounding_box)
    executor.reset_ui(page, ctx)

    assert timeouts == ([remaining_ms] if remaining_ms else [])
    assert calls == ([("press", "Escape"), ("click", 188, 140)] if remaining_ms else [])
    assert (ctx.run_deadline, ctx.op_deadline) == (run_deadline, op_deadline)


def test_cleanup_does_not_click_after_canvas_lookup_exhausts_budget(monkeypatch, tmp_path):
    now = [100]
    monkeypatch.setattr(executor.time, "monotonic", lambda: now[0])
    calls = []
    page = FakePage(calls)

    def bounding_box(*, timeout=None):
        assert timeout == 10000
        now[0] = 111
        return FakeCanvas().bounding_box()

    monkeypatch.setattr(page.canvas, "bounding_box", bounding_box)
    executor.reset_ui(page, cleanup_context(tmp_path))

    assert calls == [("press", "Escape")]


@pytest.mark.parametrize(
    ("failed_ops", "expected_status", "expected_exit"),
    [([], "ok", 0), (["s002"], "partial", 0), (["s004"], "failed", 1),
     (["s003"], "failed", 1)],
)
def test_status_depends_on_required_report_milestones(
    fake_driver, monkeypatch, tmp_path, failed_ops, expected_status, expected_exit
):
    _page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls, fail_run={op_id: 2 for op_id in failed_ops})
    recipe = make_recipe(tmp_path, "open_report", "set_canvas", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == expected_exit
    assert read_events(stream)[-1]["status"] == expected_status
    if "s003" in failed_ops:
        assert ("run", "get_link", "s004") in calls


def test_not_signed_in_exits_three_without_starting_ops(fake_driver, monkeypatch, tmp_path):
    _page, calls, events, stream = fake_driver
    monkeypatch.setattr(executor.chrome, "check", lambda _config: {"signed_in": False})
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 3

    records = read_events(stream)
    assert [event["event"] for event in records] == ["run_started", "log", "run_finished"]
    assert records[-1]["status"] == "failed"
    assert records[-1]["error_code"] == "not_signed_in"
    assert calls == []


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("signed_in", [False, True])
def test_browser_is_started_or_reused_before_sign_in_check(
    fake_driver, monkeypatch, tmp_path, running, signed_in
):
    page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls)
    config = executor.chrome.ChromeConfig.from_env()
    version = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/test"}
    startup = []
    if running:
        config.profile.mkdir()
        config.marker.write_text(json.dumps({
            "websocket": version["webSocketDebuggerUrl"], "port": config.port,
        }))
    versions = iter([version] if running else [None, version])
    monkeypatch.setattr(executor.chrome, "_version", lambda _config: next(versions))
    monkeypatch.setattr(executor.chrome, "_port_busy", lambda _config: False)
    monkeypatch.setattr(executor.chrome, "chrome_path", lambda: "chrome.exe")

    def launch(args, **_kwargs):
        assert not running, "running owned browser must be reused"
        startup.append("launch")
        assert f"--user-data-dir={config.profile}" in args
        assert f"--app={executor.chrome.STUDIO_URL}" in args

    def check(actual_config):
        assert actual_config == config
        assert config.marker.is_file()
        assert startup == ([] if running else ["launch"])
        startup.append("check")
        return {"chrome_running": True, "signed_in": signed_in}

    monkeypatch.setattr(executor.chrome.subprocess, "Popen", launch)
    monkeypatch.setattr(executor.chrome, "ensure_browser", ensure_browser)
    monkeypatch.setattr(executor.chrome, "check", check)
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == (0 if signed_in else 3)
    assert next(versions, None) is None
    assert startup == (["check"] if running else ["launch", "check"])
    assert read_events(stream)[-1]["error_code"] == (None if signed_in else "not_signed_in")
    assert page.closed == signed_in
    if not signed_in:
        assert calls == []


@pytest.mark.parametrize("failure, message", [
    ("missing_chrome", "DSS_CHROME_PATH"),
    ("launch_error", "Cannot start Chrome"),
    ("busy_port", "DSS_CDP_PORT is busy"),
    ("unrecognized_browser", "unrecognized browser"),
    ("stale_marker", "unrecognized browser"),
])
def test_browser_startup_failures_remain_browser_errors(
    fake_driver, monkeypatch, tmp_path, failure, message
):
    page, calls, events, stream = fake_driver
    config = executor.chrome.ChromeConfig.from_env()
    version = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/foreign"}
    if failure == "stale_marker":
        config.profile.mkdir()
        config.marker.write_text(json.dumps({
            "websocket": "ws://127.0.0.1:9222/devtools/browser/old", "port": config.port,
        }))
    monkeypatch.setattr(executor.chrome, "_version", lambda _config: (
        version if failure in {"unrecognized_browser", "stale_marker"} else None
    ))
    monkeypatch.setattr(executor.chrome, "_port_busy", lambda _config: failure == "busy_port")
    if failure == "missing_chrome":
        monkeypatch.setenv("DSS_CHROME_PATH", str(tmp_path / "missing-chrome.exe"))
    else:
        monkeypatch.setattr(executor.chrome, "chrome_path", lambda: "chrome.exe")

    def launch(*_args, **_kwargs):
        assert failure == "launch_error", "must reject the port before launching"
        raise OSError("cannot launch")

    monkeypatch.setattr(executor.chrome.subprocess, "Popen", launch)
    monkeypatch.setattr(executor.chrome, "ensure_browser", ensure_browser)
    monkeypatch.setattr(executor.chrome, "check", lambda _config: pytest.fail("sign-in check"))
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 1
    records = read_events(stream)
    assert [event["event"] for event in records] == ["run_started", "log", "run_finished"]
    assert message in records[-2]["message"]
    assert records[-1]["error_code"] == "browser_error"
    assert calls == []
    assert not page.closed


def test_dry_run_never_starts_or_checks_browser(fake_driver, monkeypatch, tmp_path):
    _page, calls, events, stream = fake_driver
    monkeypatch.setattr(executor.chrome, "ensure_browser", lambda _config: pytest.fail("browser launch"))
    monkeypatch.setattr(executor.chrome, "check", lambda _config: pytest.fail("browser check"))
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")

    assert executor.run_recipe(recipe, events, dry_run=True) == 0
    assert read_events(stream)[-1]["status"] == "ok"
    assert read_events(stream)[-1]["skipped"] == 3
    assert calls == []


def test_empty_recipe_succeeds_without_browser(fake_driver, monkeypatch, tmp_path):
    _page, calls, events, stream = fake_driver
    monkeypatch.setattr(executor.chrome, "ensure_browser", lambda _config: pytest.fail("browser launch"))
    monkeypatch.setattr(executor.chrome, "check", lambda _config: pytest.fail("browser check"))
    recipe = make_recipe(tmp_path)

    assert executor.run_recipe(recipe, events) == 0
    assert read_events(stream)[-1]["status"] == "ok"
    assert calls == []


def test_missing_billing_project_fails_before_browser_check(fake_driver, monkeypatch, tmp_path):
    _page, _calls, events, stream = fake_driver
    monkeypatch.setattr(executor, "build_url", lambda _header: (_ for _ in ()).throw(
        ValueError("GCP_PROJECT_ID is required before opening Chrome")))
    monkeypatch.setattr(executor.chrome, "check", lambda _config: pytest.fail("browser check"))
    monkeypatch.setattr(executor.chrome, "ensure_browser", lambda _config: pytest.fail("browser launch"))
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 1
    records = read_events(stream)
    assert records[-1]["error_code"] == "configuration_error"
    assert records[-1]["skipped"] == 3


def test_timeout_skips_new_ops_but_attempts_save_and_link(fake_driver, monkeypatch, tmp_path):
    _page, calls, events, stream = fake_driver
    install_handler(monkeypatch, calls)
    recipe = make_recipe(tmp_path, "open_report", "set_canvas", "save_report", "get_link")

    assert executor.run_recipe(recipe, events, timeout=0) == 1

    records = read_events(stream)
    op_events = [event for event in records if event["event"].startswith("op_")]
    assert [(event["event"], event["op_id"]) for event in op_events] == [
        ("op_started", "s001"), ("op_finished", "s001"),
        ("op_started", "s002"), ("op_finished", "s002"),
        ("op_started", "s003"), ("op_finished", "s003"),
        ("op_started", "s004"), ("op_finished", "s004"),
    ]
    skipped = [event for event in op_events if event["event"] == "op_finished"
               and event["status"] == "skipped"]
    assert [event["op_id"] for event in skipped] == ["s001", "s002"]
    assert all(event["message"] == "run timeout before execution" for event in skipped)
    assert not any(call[0] == "run" and call[2] in {"s001", "s002"} for call in calls)
    assert ("run", "save_report", "s003") in calls
    assert ("run", "get_link", "s004") in calls
    assert records[-1]["error_code"] == "timeout"
    assert records[-1]["status"] == "failed"
