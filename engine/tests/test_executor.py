import io
import json
import re
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

    def evaluate(self, expression, box, *, timeout=None):
        # charts._reveal: the whole canvas is already in view.
        return {"x": 200, "y": 100, "view": {"left": 0, "top": 0, "right": 1920, "bottom": 1200}}


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


class ImageHandle:
    def __init__(self, name, box=(0, 0, 1200, 900), loaded=True):
        self.name, self.box, self.loaded = name, box, loaded

    def element_handle(self, *, timeout):
        return self

    def wait_for_selector(self, selector, *, state, timeout):
        assert selector == "image_content" and state == "visible"
        return self

    def evaluate(self, expression):
        if "naturalWidth" in expression:
            return 1200 if self.loaded else 0
        assert "offsetLeft" in expression
        return self.box

    def dispose(self):
        pass


class ImageCollection:
    def __init__(self, page, *, charts=False):
        self.page, self.charts = page, charts

    @property
    def items(self):
        return [c for c in self.page.items if not self.charts or c.name == "chart"]

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]

    def evaluate_all(self, expression, handle):
        assert "indexOf(retained)" in expression
        return self.items.index(handle) if handle in self.items else -1


class ImagePage:
    def __init__(self):
        self.items = [ImageHandle("ordinary"), ImageHandle("text"),
                      ImageHandle("control"), ImageHandle("chart")]
        self.uploads = 0
        self.selected = None
        self.menu_open = False
        self.closing = False
        self.raise_after_upload = False
        self.keyboard = self
        self.mouse = self

    def press(self, key):
        if key == "Escape" and not self.closing:
            self.menu_open = False

    def click(self, x, y):
        # The empty workspace left of the canvas deselects, unless a closing
        # menu absorbs the click (live 2026-10-21, right after Send to back).
        if self.menu_open:
            self.menu_open = False
        else:
            self.selected = None

    def wait_for_timeout(self, timeout):
        if self.closing:
            self.menu_open = self.closing = False

    def locator(self, selector):
        if selector in {"components", "chart_components"}:
            return ImageCollection(self, charts=selector == "chart_components")
        if selector in {"selected_component", "open_menu"}:
            shown = self.selected is not None if selector == "selected_component" else self.menu_open
            return SelectionState(shown)
        assert selector in {"image", "upload_image", "arrange", "order", "send_back"}
        return ImageAction(self, selector)

    @contextmanager
    def expect_file_chooser(self, *, timeout):
        from types import SimpleNamespace
        yield SimpleNamespace(value=self)

    def set_files(self, path, *, timeout):
        self.uploads += 1
        self.items.append(ImageHandle(f"background{self.uploads}"))
        if self.raise_after_upload:
            self.raise_after_upload = False
            raise RuntimeError("transient file chooser failure after upload")


class SelectionState:
    def __init__(self, shown):
        self.shown = shown

    def count(self):
        return int(self.shown)

    def nth(self, index):
        return self

    def is_visible(self):
        return self.shown


class ImageAction:
    def __init__(self, page, key):
        self.page, self.key = page, key

    def click(self, *, timeout):
        # Send to back's menu is still closing (visible) when the click returns.
        self.page.menu_open = self.key in {"arrange", "send_back"}
        self.page.closing = self.key == "send_back"
        if self.key == "send_back":
            self.page.items.remove(self.page.selected)
            self.page.items.insert(0, self.page.selected)

    def hover(self, *, timeout):
        assert self.key == "order"


@pytest.fixture
def background_driver(tmp_path, monkeypatch):
    import time
    from dsengine.ops import pages, report

    recipe = make_recipe(tmp_path)
    recipe.ops = [
        Operation(id="s001", op="add_image", component_id="ordinary"),
        Operation(id="s002", op="add_text", component_id="text"),
        Operation(id="s003", op="add_control", component_id="control"),
        Operation(id="s004", op="add_chart", component_id="chart"),
        Operation(id="s005", op="set_background_image", path="background.png",
                  x=0, y=0, w=400, h=400),
        Operation(id="s006", op="set_background_image", path="background.png",
                  x=1100, y=800, w=400, h=400),
        Operation(id="s007", op="set_style", component_id="ordinary", style={}),
    ]
    (tmp_path / "background.png").write_bytes(b"fixture")
    ctx = OpContext(recipe, {key: key for key in (
        "components", "chart_components", "image", "upload_image", "arrange", "order",
        "send_back", "image_content", "canvas", "selected_component", "open_menu")},
        EventWriter(io.StringIO()), tmp_path,
        time.monotonic() + 60, op_deadline=time.monotonic() + 20)
    ctx.state = {"s001": {"component_index": 0, "target": (0, 0, 1200, 900)},
                 "s002": {"component_index": 1, "target": (0, 0, 1200, 900)},
                 "s003": {"control_index": 2, "target": (0, 0, 1200, 900)},
                 "s004": {"chart_index": 0, "target": (0, 0, 1200, 900)}}
    ctx.state["_source_fields"] = ["status", "id"]
    page = ImagePage()
    monkeypatch.setattr(pages, "current", lambda _page, _ctx: (1, 2))
    monkeypatch.setattr(pages, "switch", lambda _page, _ctx, index: None)
    monkeypatch.setattr(report, "_prepare_image", lambda _page, component, _ctx:
                        setattr(_page, "selected", component))
    monkeypatch.setattr(report, "_place_component", lambda _page, _ctx, component, canvas, box:
                        setattr(component, "box", box))
    original_locator = report._locator
    monkeypatch.setattr(report, "_locator", lambda p, c, key:
                        FakeCanvas() if key == "canvas" else original_locator(p, c, key))
    return page, ctx


def test_background_retry_after_upload_keeps_one_scoped_component(background_driver):
    from dsengine.ops import report

    page, ctx = background_driver
    page.raise_after_upload = True
    op = ctx.recipe.ops[4]
    with pytest.raises(RuntimeError, match="transient"):
        report.run(page, op, ctx)
    assert ctx.state[op.id]["upload_started"]
    assert ctx.state[op.id]["page_index"] == 1
    report.run(page, op, ctx)
    report.verify(page, op, ctx)
    assert page.uploads == 1 and len(page.items) == 5
    assert page.items[0].name == "background1"
    assert page.items[0].box == (0, 0, 400, 400)
    assert page.items[1].name == "ordinary" and page.items[1].box == (0, 0, 1200, 900)


def test_multiple_backgrounds_reindex_registry_and_clamp_box(background_driver):
    from dsengine.ops import report, style

    page, ctx = background_driver
    ordinary, text, control, chart = page.items
    for op in ctx.recipe.ops[4:6]:
        report.run(page, op, ctx)
        report.verify(page, op, ctx)
    assert page.uploads == 2 and len(page.items) == 6
    assert [c.name for c in page.items[:2]] == ["background2", "background1"]
    assert page.items[0].box == (1100, 800, 100, 100)
    assert ctx.state["s005"]["component_index"] == 1
    assert ctx.state["s006"]["component_index"] == 0
    assert ctx.state["s002"]["component_index"] == 3
    assert ctx.state["s003"]["control_index"] == 4
    assert ctx.state["s004"]["chart_index"] == 0
    for component_id, expected in [("ordinary", ordinary), ("text", text),
                                    ("control", control), ("chart", chart)]:
        op = Operation(id="s007", op="set_style", component_id=component_id, style={})
        # Style lookup must retain the intended creator after both paint-order changes.
        expected.wait_for = lambda **kwargs: None
        component, _ = style.component_for(page, op, ctx)
        assert component is expected


def test_background_verification_rejects_an_unrelated_first_image(background_driver):
    from dsengine.ops import OperationError, report

    page, ctx = background_driver
    op = ctx.recipe.ops[4]
    report.run(page, op, ctx)
    page.items.insert(0, page.items.pop(1))
    ctx.op_deadline = 0
    with pytest.raises(OperationError, match="did not verify"):
        report.verify(page, op, ctx)


def test_background_retry_reuses_creation_after_send_to_back(background_driver):
    from dsengine.ops import report

    page, ctx = background_driver
    op = ctx.recipe.ops[4]
    report.run(page, op, ctx)
    retained = ctx.state[op.id]["component"]
    report.run(page, op, ctx)
    report.verify(page, op, ctx)
    assert page.uploads == 1 and len(page.items) == 5
    assert ctx.state[op.id]["component"] is retained
    assert ctx.state["s001"]["component_index"] == 1


@pytest.mark.parametrize("checked", [True, False])
def test_image_setup_disables_aspect_ratio_only_when_enabled(tmp_path, monkeypatch, checked):
    from types import SimpleNamespace
    from dsengine.ops import report

    calls = []
    class Control:
        def __init__(self, key):
            self.key = key

        def click(self, *, timeout):
            calls.append(("control", self.key))

        def wait_for(self, *, state, timeout):
            assert state == "visible"

        def get_attribute(self, name):
            assert name == "aria-checked"
            return str(checked).lower()

    controls = {k: Control(k) for k in ("selection_mode", "setup_tab", "image_preserve_ratio")}
    controls["canvas"] = FakeCanvas()
    monkeypatch.setattr(report, "_locator", lambda page, ctx, key: controls[key])
    component = SimpleNamespace(click=lambda *, position, timeout: calls.append(("image", position)))
    page = SimpleNamespace(mouse=FakeMouse(calls))
    report._prepare_image(page, component, cleanup_context(tmp_path))
    assert calls == [("control", "selection_mode"), ("click", 188, 140),
                     ("image", {"x": 10, "y": 10}), ("control", "setup_tab")] + (
                         [("control", "image_preserve_ratio")] if checked else [])


def test_background_reordering_leaves_other_pages_registry_untouched(background_driver):
    from dsengine.ops import report

    page, ctx = background_driver
    ctx.state["other_page"] = {"page_index": 2, "component_index": 99}
    report.run(page, ctx.recipe.ops[4], ctx)
    assert ctx.state["other_page"] == {"page_index": 2, "component_index": 99}


def test_image_is_resized_before_moving_to_clamped_canvas_edge(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from dsengine.ops import charts, report

    calls, drags = [], []
    component = ImageHandle("background", (0, 0, 333, 250))
    component.bounding_box = lambda: dict(zip(("x", "y", "width", "height"),
        (200 + component.box[0], 100 + component.box[1], *component.box[2:])))
    canvas = FakeCanvas()

    def drag(page, start, end):
        drags.append((start, end))
        x, y, w, h = component.box
        if start == (200 + x + w, 100 + y + h):
            assert x + w <= 1200 and y + h <= 900, "resize handle must be inside the canvas"
            component.box = (x, y, end[0] - 200 - x, end[1] - 100 - y)
        else:
            component.box = (x + end[0] - start[0], y + end[1] - start[1], w, h)

    monkeypatch.setattr(charts, "_drag", drag)
    page = SimpleNamespace(mouse=FakeMouse(calls))
    report._place_component(page, cleanup_context(tmp_path), component, canvas, (1100, 800, 100, 100))
    assert drags == [((533, 350), (300, 200)), ((250, 150), (1350, 950))]
    assert component.box == (1100, 800, 100, 100)


class ScrollingCanvas:
    """A tall canvas in the live editor's scroll window at 1920 x 1200 (2026-10-21).

    The window spans viewport y 162-1200 and x 0-1440; the canvas top sits 22 px
    below the scroll origin, at x 116. Revealing aligns the box's top 40 px inside.
    """

    def __init__(self, height):
        self.height, self.scroll = height, 0

    def origin(self):
        return 116, 184 - self.scroll

    def bounding_box(self, *, timeout=None):
        x, y = self.origin()
        return {"x": x, "y": y, "width": 1200, "height": self.height}

    def evaluate(self, expression, box, *, timeout=None):
        _left, top, _right, bottom, edge = box
        y = self.origin()[1]
        if y + top < 162 + edge or y + bottom > 1200 - edge:
            self.scroll = max(0, min(self.height + 48 - 1038, top + 22 - edge))
        x, y = self.origin()
        return {"x": x, "y": y, "view": {"left": 0, "top": 162, "right": 1440, "bottom": 1200}}


class Placed:
    def __init__(self, canvas, box):
        self.canvas, self.box = canvas, box

    def evaluate(self, expression):
        assert "offsetLeft" in expression
        return self.box

    def bounding_box(self):
        x, y = self.canvas.origin()
        return {"x": x + self.box[0], "y": y + self.box[1], "width": self.box[2], "height": self.box[3]}


def _in_view(point):
    return 0 <= point[0] <= 1440 and 162 <= point[1] <= 1200


def _scrolling_editor(monkeypatch, canvas, component):
    """Mouse input reaches the editor only inside its scroll window (live 2026-10-21)."""
    from types import SimpleNamespace
    from dsengine.ops import charts

    events = []

    def drag(page, start, end):
        events.append(("drag", start, end))
        assert all(_in_view(p) for p in (start, (start[0] + 10, start[1] + 10), end)), events
        ox, oy = canvas.origin()
        x, y, w, h = component.box
        dx, dy = end[0] - start[0], end[1] - start[1]
        if (start[0] - ox, start[1] - oy) == (x + w, y + h):
            assert x + w + dx <= 1200 and y + h + dy <= canvas.height, "handle left the canvas"
            component.box = (x, y, w + dx, h + dy)
        else:
            assert x <= start[0] - ox <= x + w and y <= start[1] - oy <= y + h, "drag missed"
            component.box = (x + dx, y + dy, w, h)

    def click(x, y):
        events.append(("click", x, y))
        assert _in_view((x, y)), events

    monkeypatch.setattr(charts, "_drag", drag)
    return SimpleNamespace(mouse=SimpleNamespace(click=click),
                           keyboard=FakeKeyboard(events)), events


def test_full_canvas_background_is_placed_with_every_drag_in_view(tmp_path, monkeypatch):
    # Release b_b2ac19ea6696 page 3: background_p3.png (1200 x 1492) was uploaded
    # at 400,394 at a reduced size; the move started at the resized image's
    # center below the window, missed, and the op timed out at its upload box.
    from dsengine.ops import report

    canvas = ScrollingCanvas(1492)
    image = Placed(canvas, (400, 394, 201, 250))
    page, events = _scrolling_editor(monkeypatch, canvas, image)
    ctx = cleanup_context(tmp_path)
    ctx.canvas_dimensions = (1200, 1492)
    report._place_component(page, ctx, image, canvas, (0, 0, 1200, 1492))
    assert image.box == (0, 0, 1200, 1492)
    assert sum(event[0] == "drag" for event in events) == 3  # move, then two resize steps


@pytest.mark.parametrize("target", [(24, 884, 1152, 304), (24, 1204, 568, 264)])
def test_chart_below_the_fold_is_placed_with_every_drag_in_view(tmp_path, monkeypatch, target):
    # Release page 3: the table's resize handle started below the window (drawn
    # ~400 px wide) and the bar at y 1204 timed out; insertion clicks at 24,24
    # after the canvas had scrolled opened a "Choose a field" filter chip.
    from dsengine.ops import charts

    canvas = ScrollingCanvas(1492)
    canvas.scroll = 300
    chart = Placed(canvas, (24, 24, 400, 230))
    page, events = _scrolling_editor(monkeypatch, canvas, chart)
    ctx = cleanup_context(tmp_path)
    charts._click_canvas(page, ctx, canvas, 24, 24)
    assert events[0] == ("click", 140, 202)  # inside the canvas, not the filter bar
    charts._place_chart(page, ctx, chart, canvas, target)
    assert chart.box == target


def test_background_ends_with_no_menu_open_and_nothing_selected(background_driver):
    # Release page 3: Image properties and the Arrange > Order menu stayed open;
    # the next add_chart left the image selected and opened a filter chip.
    from dsengine.ops import OperationError, report

    page, ctx = background_driver
    op = ctx.recipe.ops[4]
    report.run(page, op, ctx)
    assert page.selected is None and not page.menu_open
    report.verify(page, op, ctx)

    ctx.op_deadline = 0
    page.menu_open = True
    with pytest.raises(OperationError, match="did not verify"):
        report.verify(page, op, ctx)
    page.menu_open, page.selected = False, page.items[0]
    with pytest.raises(OperationError, match="did not verify"):
        report.verify(page, op, ctx)


def test_open_report_retains_fields_when_image_selection_clears_data_panel(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from dsengine.ops import OperationError, charts, report

    fields = ["status", "sale_price", "created_at"]
    ctx = cleanup_context(tmp_path)
    ctx.open_url = "https://datastudio.google.com/reporting/create"
    ctx.selectors = {key: key for key in ("field_buttons", "zoom_menu", "zoom_100", "canvas")}
    controls = {
        "field_buttons": SimpleNamespace(evaluate_all=lambda expression: list(fields)),
        "zoom_menu": SimpleNamespace(click=lambda **kwargs: None),
        "zoom_100": SimpleNamespace(click=lambda **kwargs: None),
        "canvas": object(),
    }
    page = SimpleNamespace(
        goto=lambda *args, **kwargs: None, set_viewport_size=lambda size: None,
        evaluate=lambda expression: [1920, 1200, 2],
        locator=lambda selector: controls[selector],
        url="https://datastudio.google.com/reporting/create",
    )
    monkeypatch.setattr(report, "_wait_for_editor", lambda page, ctx: None)
    monkeypatch.setattr(report, "_wait_visible", lambda locator, ctx: None)
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    report.run(page, Operation(id="s001", op="open_report"), ctx)

    fields.clear()  # Live image Setup removes source-field chips from the DOM.
    charts._require_source_field(page, ctx, "sale_price")
    charts._require_source_field(page, ctx, "created_at")
    with pytest.raises(OperationError, match="field __missing__ not in data source"):
        charts._require_source_field(page, ctx, "__missing__")


@pytest.mark.parametrize("layout", [[3840, 2400, 0.5], [1440, 810, 1], [1920, 1100, 1]])
def test_open_report_fails_clearly_when_chrome_zoom_shrinks_the_editor(tmp_path, monkeypatch, layout):
    # Live 2026-10-21: a persisted 50% Chrome zoom laid the editor out at
    # 3840 x 2400 CSS px; every chart field picker then lacked "Chart fields".
    from types import SimpleNamespace
    from dsengine.ops import OperationError, report

    ctx = cleanup_context(tmp_path)
    ctx.open_url = "https://datastudio.google.com/reporting/create"
    sizes = []
    zoom = []
    page = SimpleNamespace(
        goto=lambda *args, **kwargs: None, set_viewport_size=sizes.append,
        evaluate=lambda expression: list(layout),
        locator=lambda selector: SimpleNamespace(click=lambda **kwargs: zoom.append(selector)),
    )
    ctx.selectors = {key: key for key in ("field_buttons", "zoom_menu", "zoom_100", "canvas")}
    monkeypatch.setattr(report, "_wait_for_editor", lambda page, ctx: None)
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    expected = f"editor laid out at {layout[0]} x {layout[1]} CSS px .*Ctrl\\+0"
    with pytest.raises(OperationError, match=expected):
        report.run(page, Operation(id="s001", op="open_report"), ctx)
    assert sizes == [{"width": 1920, "height": 1200}]
    assert zoom == []  # No editor interaction on a mis-sized layout.


def test_zoomed_layout_aborts_the_run_with_its_message(fake_driver, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from dsengine.ops import report

    _page, calls, events, stream = fake_driver
    handler = install_handler(monkeypatch, calls)

    def zoomed(page, op, ctx):
        calls.append(("run", op.op, op.id))
        report._check_layout(SimpleNamespace(evaluate=lambda expression: [3840, 2400, 0.5]))

    handler.run = zoomed
    recipe = make_recipe(tmp_path, "open_report", "set_canvas", "save_report", "get_link")

    assert executor.run_recipe(recipe, events) == 1

    records = read_events(stream)
    opened = next(r for r in records if r["event"] == "op_finished" and r["op_id"] == "s001")
    assert opened["status"] == "failed"
    assert opened["message"].startswith("editor laid out at 3840 x 2400 CSS px (devicePixelRatio 0.5)")
    assert "Ctrl+0" in opened["message"]
    assert records[-1]["error_code"] == "open_report_failed"
    assert ("run", "set_canvas", "s002") not in calls


def test_title_font_verification_waits_for_option_list_to_disappear(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from dsengine.ops import OperationError, style

    ctx = cleanup_context(tmp_path)
    creator = Operation(id="s001", op="add_chart", component_id="sales")
    op = Operation(id="s002", op="set_style", component_id="sales", style={"font_size": 8})
    ctx.recipe.ops = [creator, op]
    ctx.state[op.id] = {"applied": {"font_size": 8}, "creator": creator.id}
    labels = iter(["8px\n8px\n9px", "8px"])
    title = SimpleNamespace(inner_text=lambda **kwargs: next(labels, "8px"))
    waits = []
    page = SimpleNamespace(wait_for_timeout=waits.append)
    monkeypatch.setattr(style, "_locator", lambda page, ctx, key: title)
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    style.verify(page, op, ctx)
    assert waits and all(wait <= 1000 for wait in waits)

    # A different selected size must still fail, even if it contains "8px".
    title.inner_text = lambda **kwargs: "18px"
    ctx.op_deadline = 100
    with pytest.raises(OperationError, match="title font_size did not verify"):
        style.verify(page, op, ctx)


class ReviewControl:
    def __init__(self, dialog, key, present=True):
        self.dialog, self.key, self._present = dialog, key, present

    @property
    def present(self):
        return self._present and (self.key != "review_accept"
                                 or self.dialog.ticks >= self.dialog.checkbox_after)

    def count(self):
        return int(self.present)

    def nth(self, index):
        return self

    def is_visible(self):
        return self.present and self.dialog.open

    def is_checked(self):
        return self.dialog.checked

    def is_enabled(self):
        return (self.dialog.ticks >= self.dialog.enabled_after
                and (self.dialog.checked or not self.dialog.checkbox))

    def check(self, *, timeout):
        assert self.present and self.dialog.open
        self.dialog.calls.append(("check", self.dialog.name))
        self.dialog.checked = True

    def click(self, *, timeout):
        assert self.dialog.open
        assert self.is_enabled(), "clicked disabled acknowledgement instead of rechecking controls"
        self.dialog.calls.append(("click", self.key))
        # The old variant keeps its button disabled until the risk is accepted.
        assert self.dialog.checked or not self.dialog.checkbox, "risk checkbox left unticked"
        self.dialog.open = False


class ReviewDialog:
    def __init__(self, calls, name, button, *, checkbox, checkbox_after=0, enabled_after=0):
        self.calls, self.name, self.button, self.checkbox = calls, name, button, checkbox
        self.open, self.checked = True, False
        self.ticks, self.checkbox_after, self.enabled_after = 0, checkbox_after, enabled_after

    def count(self):
        return 1

    def nth(self, index):
        return self

    def is_visible(self):
        return self.open

    def locator(self, selector):
        # Only the dialog's own checkbox and button exist in this scope (no Close).
        if selector == "review_accept":
            return ReviewControl(self, selector, self.checkbox)
        assert selector == self.button, f"unexpected control in review dialog: {selector}"
        return ReviewControl(self, selector)

    def wait_for(self, *, state, timeout):
        assert self.open == (state == "visible")


class ReadyWhenClosed:
    def __init__(self, dialog):
        self.dialog = dialog

    def count(self):
        return 1

    def nth(self, index):
        return self

    def is_visible(self):
        return self.dialog is not None and not self.dialog.open


def review_context(tmp_path, monkeypatch, *keys):
    monkeypatch.setattr(executor.time, "monotonic", lambda: 100)
    ctx = cleanup_context(tmp_path)
    ctx.selectors = {key: key for key in ("review_accept", *keys)}
    return ctx


@pytest.mark.parametrize("checkbox", [True, False])
def test_create_review_dialog_is_accepted_with_or_without_checkbox(tmp_path, monkeypatch, checkbox):
    from types import SimpleNamespace
    from dsengine.ops import report

    calls = []
    dialog = ReviewDialog(calls, "create", "review_acknowledge", checkbox=checkbox)
    controls = {"review_dialog": dialog, "add_chart": ReadyWhenClosed(dialog),
                "first_field": ReadyWhenClosed(dialog), "linking_error": ReadyWhenClosed(None)}
    def wait_for_timeout(ms):
        # The clock is frozen, so fail fast instead of polling forever.
        calls.append(("wait", ms))
        assert len(calls) < 20, "editor never became ready"

    page = SimpleNamespace(locator=lambda selector: controls[selector],
                           wait_for_timeout=wait_for_timeout)
    ctx = review_context(tmp_path, monkeypatch, *controls, "review_acknowledge")
    report._wait_for_editor(page, ctx)
    clicks = [call for call in calls if call[0] in {"click", "check"}]
    assert clicks == ([("check", "create")] if checkbox else []) + [("click", "review_acknowledge")]


@pytest.mark.parametrize("checkbox", [True, False])
def test_save_review_dialog_is_accepted_with_or_without_checkbox(tmp_path, monkeypatch, checkbox):
    from types import SimpleNamespace
    from dsengine.ops import report

    calls = []
    dialog = ReviewDialog(calls, "save", "acknowledge_save", checkbox=checkbox)

    def wait_for_url(pattern, *, timeout):
        assert not dialog.open, "report saved while the review dialog was open"
        page.url = "https://datastudio.google.com/reporting/abc123/page/p_1/edit"
        assert pattern.fullmatch(page.url)

    save_share = SimpleNamespace(click=lambda *, timeout: calls.append(("click", "save_share")))
    controls = {"save_share": save_share, "review_save_dialog": dialog}
    page = SimpleNamespace(url="https://datastudio.google.com/reporting/create",
                           locator=lambda selector: controls[selector], wait_for_url=wait_for_url)
    ctx = review_context(tmp_path, monkeypatch, *controls, "acknowledge_save")
    op = Operation(id="s002", op="save_report")
    report.run(page, op, ctx)
    report.verify(page, op, ctx)
    assert ctx.report_url == "https://datastudio.google.com/reporting/abc123/page/p_1"
    assert calls == [("click", "save_share")] + (
        [("check", "save")] if checkbox else []) + [("click", "acknowledge_save")]


def test_review_dialog_selectors_match_exact_names():
    from dsengine.selectors import load_selectors

    selectors = load_selectors()
    # Role names match case-insensitive substrings unless suffixed with "s":
    # "Review data access" would also match "Review data access before saving".
    assert selectors["review_dialog"] == 'role=dialog[name="Review data access"s]'
    assert selectors["review_save_dialog"] == 'role=dialog[name="Review data access before saving"s]'
    assert selectors["review_acknowledge"] == 'role=button[name="Acknowledge"s]'


@pytest.mark.parametrize("stage", ["create", "save"])
@pytest.mark.parametrize("variant", ["late-checkbox", "late-button", "op-exhausted", "run-exhausted"])
def test_review_controls_become_ready_within_shared_budget(tmp_path, monkeypatch, stage, variant):
    from types import SimpleNamespace
    from dsengine.ops import OperationError, report

    calls = []
    button = "review_acknowledge" if stage == "create" else "acknowledge_save"
    exhausted = variant.endswith("exhausted")
    checkbox = variant != "late-button"
    dialog = ReviewDialog(calls, stage, button, checkbox=checkbox,
                          checkbox_after=100 if exhausted else 2,
                          enabled_after=2)
    controls = {"review_dialog": dialog, "review_save_dialog": dialog,
                "add_chart": ReadyWhenClosed(dialog), "first_field": ReadyWhenClosed(dialog),
                "linking_error": ReadyWhenClosed(None),
                "save_share": SimpleNamespace(click=lambda **kw: calls.append(("click", "save_share")))}
    now = [100.0]

    def wait(ms):
        assert 0 < ms <= 250
        now[0] += ms / 1000
        dialog.ticks += 1
        assert dialog.ticks < 10, "readiness polling exceeded its budget"

    def saved_url(pattern, **kwargs):
        assert not dialog.open
        page.url = "https://datastudio.google.com/reporting/abc123/page/p_1/edit"
        assert pattern.fullmatch(page.url)

    page = SimpleNamespace(locator=lambda selector: controls[selector],
                           wait_for_timeout=wait, wait_for_url=saved_url)
    ctx = review_context(tmp_path, monkeypatch, *controls, button)
    monkeypatch.setattr(report.time, "monotonic", lambda: now[0])
    ctx.op_deadline = 100.6 if variant == "op-exhausted" else 105
    ctx.run_deadline = 100.6 if variant == "run-exhausted" else 110
    deadlines = (ctx.op_deadline, ctx.run_deadline)

    def run():
        if stage == "create":
            report._wait_for_editor(page, ctx)
        else:
            report.run(page, Operation(id="s002", op="save_report"), ctx)

    if exhausted:
        with pytest.raises(OperationError, match="data-access review controls did not become ready"):
            run()
        assert dialog.open and not dialog.checked
        assert not any(call == ("click", button) for call in calls)
        assert now[0] <= 100.601
    else:
        run()
        assert dialog.ticks == 2
        assert not dialog.open
        actions = [call for call in calls if call[0] in {"click", "check"}]
        assert actions == ([("click", "save_share")] if stage == "save" else []) + (
            [("check", stage)] if checkbox else []) + [("click", button)]
    assert (ctx.op_deadline, ctx.run_deadline) == deadlines


def _time_series(sort, **extra):
    return Operation(id="s011", op="add_chart", component_id="p1_trend", chart_type="time_series",
                     x=24, y=424, w=1152, h=264, dimensions=[], date_dimension="order_date",
                     metrics=[{"field": "quantity", "agg": "sum"},
                              {"field": "order_id", "agg": "count_distinct"}],
                     sort=sort, **extra)


def test_time_series_date_sort_is_inherent_not_a_setup_control():
    # Live 2026-10-21: time series Setup has no Sort section, so the release
    # recipe's {order_date, asc} sort waited 20 s for sort controls.
    from dsengine.ops import charts

    op = _time_series({"field": "order_date", "order": "asc"})
    assert charts._inherent_sort(op, charts._dimensions(op)[0]) is True
    bar = Operation(id="s019", op="add_chart", chart_type="bar", dimensions=["region"],
                    metrics=[{"field": "revenue", "agg": "sum"}],
                    sort={"field": "revenue", "order": "desc"})
    assert charts._inherent_sort(bar, ["region"]) is False
    assert charts._inherent_sort(_time_series(None), ["order_date"]) is False


@pytest.mark.parametrize("sort", [{"field": "order_date", "order": "desc"},
                                  {"field": "quantity", "order": "asc"}])
def test_impossible_time_series_sort_fails_before_inserting_a_chart(tmp_path, sort):
    from dsengine.ops import OperationError, charts

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"page.{name} used before sort validation")

    ctx = cleanup_context(tmp_path)
    with pytest.raises(OperationError, match="time_series sorts only by its date dimension, ascending"):
        charts.run(Untouchable(), _time_series(sort), ctx)


def test_field_picker_is_found_by_component_not_chart_fields_heading():
    # Live 2026-10-21: the first charts of a compiled recipe open a picker
    # headed "Default group" only; "Chart fields" lists fields already used.
    from dsengine.selectors import load_selectors

    picker = load_selectors()["field_picker"]
    assert ".cdk-overlay-pane:has(ng2-selector-dialog)" in [part.strip() for part in picker.split(",")]
    assert "Chart fields" not in picker


def test_canvas_size_options_match_exact_text_not_page_names():
    # Live 2026-10-21: text=Custom also matched the page tooltip
    # "Customer Segment Analysis" and set_canvas failed in strict mode.
    from dsengine.selectors import load_selectors

    selectors = load_selectors()
    assert selectors["canvas_size_custom"] == 'text="Custom"'
    assert selectors["canvas_size_auto"] == 'text="Auto"'


def test_rows_per_page_waits_for_the_option_list_not_any_overlay(tmp_path):
    # Release b_b2ac19ea6696 replay, s034: a pane reading "Autogenerate" was
    # already the last visible overlay when Rows per page opened, so option 10
    # was looked up in it and the op failed "Data Studio option 10 is unavailable".
    from dsengine.ops import charts

    class Node:
        def __init__(self, page, texts=(), clicks=None):
            self.page, self.texts, self.clicks = page, list(texts), clicks

        def count(self):
            return len(self.texts)

        def nth(self, index):
            return Node(self.page, [self.texts[index]], self.clicks)

        @property
        def first(self):
            return self.nth(0) if self.texts else Node(self.page)

        @property
        def last(self):
            return self.nth(-1)

        def is_visible(self):
            return bool(self.texts)

        def wait_for(self, *, state, timeout):
            assert state == "visible"

        def click(self, *, timeout):
            self.page.clicks.append(self.texts)
            self.page.listbox = self.page.listbox or self.clicks == "control"

        def locator(self, selector):
            assert selector == "dropdown_option"
            return Node(self.page, self.page.pane() if self.page.attached else [])

        def get_by_text(self, value, *, exact):
            return Node(self.page, [t for t in self.page.pane() if t == value])

    class Page:
        def __init__(self):
            self.clicks, self.listbox, self.attached = [], False, False

        def pane(self):
            return ["5", "10", "100"] if self.attached else ["Autogenerate"]

        def wait_for_timeout(self, timeout):
            self.attached = self.listbox  # the list attaches after the click returns

        def locator(self, selector):
            if selector == "rows_per_page_control":
                return Node(self, ["Rows per page"], "control")
            assert selector == "last_overlay"
            return Node(self, ["pane"])

    ctx = cleanup_context(tmp_path)
    ctx.selectors = {key: key for key in ("rows_per_page_control", "last_overlay", "dropdown_option")}
    ctx.op_deadline = executor.time.monotonic() + 5
    ctx.run_deadline = ctx.op_deadline
    page = Page()
    charts._set_dropdown(page, ctx, "rows_per_page_control", "10", "rows per page")
    assert page.clicks == [["Rows per page"], ["10"]]


# Live Rows per page menu (2026-10-22): a fixed list, no free number input.
_ROWS_OFFERED = ["1", "5", "10", "20", "25", "50", "100", "250", "500", "1000",
                 "2500", "5000", "7500", "10000", "25000", "50000"]


@pytest.mark.parametrize("requested, applied", [
    ("15", "10"), ("3", "1"), ("75", "50"), ("22", "20"), ("30", "25"),
    ("20", "20"), ("60000", "50000"), ("0", "1"),
])
def test_rows_per_page_nearest_offered_value_prefers_the_smaller_on_ties(requested, applied):
    from dsengine.ops import charts

    assert charts._nearest_option(requested, _ROWS_OFFERED) == applied
    assert charts._nearest_option("abc", _ROWS_OFFERED) is None
    assert charts._nearest_option("15", ["Autogenerate"]) is None


class Nodes:
    """A locator over a list of texts, or a function that lists them when used.

    Clicks are recorded on its page.
    """

    def __init__(self, page, texts):
        self.page, self.texts = page, texts

    @property
    def texts(self):
        return list(self.source() if callable(self.source) else self.source)

    @texts.setter
    def texts(self, texts):
        self.source = texts

    def count(self):
        return len(self.texts)

    def nth(self, index):
        return Nodes(self.page, [self.texts[index]])

    @property
    def first(self):
        return self.nth(0) if self.texts else Nodes(self.page, [])

    @property
    def last(self):
        return self.nth(-1)

    def is_visible(self):
        return bool(self.texts)

    def wait_for(self, *, state, timeout):
        assert state == "visible" and self.texts

    def click(self, *, timeout):
        self.page.clicks.append(self.texts[0])

    def evaluate_all(self, expression):
        return list(self.texts)


def test_table_rows_per_page_not_offered_applies_the_nearest_and_warns(tmp_path):
    # Release b_568901c19819 s012/s021/s038: rows_per_page 15 failed
    # "Data Studio option 15 is unavailable" and the table was never verified.
    from types import SimpleNamespace
    from dsengine.ops import charts

    class Pane(Nodes):
        def locator(self, selector):
            assert selector == "dropdown_option"
            opened = self.page.clicks[-1:] == ["rows_per_page_control"]
            return Nodes(self.page, _ROWS_OFFERED if opened else [])

        def get_by_text(self, value, *, exact):
            return Nodes(self.page, [text for text in _ROWS_OFFERED if text == value])

    class Page:
        def __init__(self):
            self.clicks = []
            self.keyboard = FakeKeyboard(self.clicks)

        def locator(self, selector):
            if selector == "last_overlay":
                return Pane(self, ["pane"])
            assert selector in {"setup_tab", "rows_per_page_control"}
            return Nodes(self, [selector])

        def wait_for_timeout(self, timeout):
            pass

    stream = io.StringIO()
    ctx = cleanup_context(tmp_path)
    ctx.events = EventWriter(stream)
    ctx.selectors = {key: key for key in (
        "setup_tab", "rows_per_page_control", "last_overlay", "dropdown_option")}
    ctx.op_deadline = executor.time.monotonic() + 5
    ctx.run_deadline = ctx.op_deadline
    page = Page()
    op = SimpleNamespace(id="s012", chart_type="table", title=None, options={"rows_per_page": 15})
    assert charts._set_title_and_options(page, ctx, op) == "10"
    assert page.clicks == ["setup_tab", "rows_per_page_control", "10"]
    warning = read_events(stream)[-1]
    assert (warning["event"], warning["level"]) == ("log", "warn")
    assert warning["message"] == "s012: rows_per_page 15 is not offered; applied 10"

    page, stream = Page(), io.StringIO()
    ctx.events = EventWriter(stream)
    op.options = {"rows_per_page": 25}
    assert charts._set_title_and_options(page, ctx, op) == "25"
    assert page.clicks[-1] == "25" and stream.getvalue() == ""


# Live order_items picker (2026-10-22): it renders 16 field buttons at most, and a
# table's own metrics are listed again above "Default group", so a sixth metric's
# field (user_id) has no button until the picker's search box filters the list.
_PICKER = ["id", "inventory_item_id", "order_id", "product_id", "sale_price",
           "created_at (Date)", "Record Count", "created_at", "delivered_at", "id",
           "inventory_item_id", "order_id", "product_id", "returned_at", "sale_price",
           "shipped_at", "status", "user_id"]


class PickerNode(Nodes):
    def locator(self, selector):
        picker = self.page
        if selector == "field_picker_search":
            return Nodes(picker, ["search"] if picker.search else [])
        assert selector == "field_picker_empty"
        return Nodes(picker, lambda: [] if picker.rendered() else ["No results"])

    def get_by_role(self, role, *, name, exact):
        assert role == "button" and exact
        return Nodes(self.page, lambda: [f for f in self.page.rendered() if f == name])


class Picker:
    """A page whose field picker renders 16 rows unless its search box filters it."""

    def __init__(self, fields, *, search=True):
        self.fields, self.search, self.query, self.open = fields, search, None, True
        self.clicks, self.fills, self.waits = [], [], 0

    def rendered(self):
        if self.query is None:
            return self.fields[:16]
        return [field for field in dict.fromkeys(self.fields) if self.query in field]

    def locator(self, selector):
        assert selector == "field_picker"
        return PickerNode(self, lambda: ["picker"] if self.open else [])

    def wait_for_timeout(self, timeout):
        self.waits += 1


@pytest.fixture
def picker_context(tmp_path, monkeypatch):
    def fill(node, text, *, timeout):
        node.page.fills.append(text)
        node.page.query = text

    def click(node, *, timeout):
        node.page.clicks.append(node.texts[0])
        if isinstance(node.page, Picker):
            node.page.open = False  # choosing a field closes the picker

    monkeypatch.setattr(Nodes, "fill", fill, raising=False)
    monkeypatch.setattr(Nodes, "click", click)
    ctx = cleanup_context(tmp_path)
    ctx.selectors = {key: key for key in (
        "field_picker", "field_picker_search", "field_picker_empty")}
    ctx.op_deadline = executor.time.monotonic() + 5
    ctx.run_deadline = ctx.op_deadline
    return ctx


@pytest.mark.parametrize("field, fills", [("user_id", ["user_id"]), ("status", ["status"]),
                                           ("shipped_at", []), ("sale_price", [])])
def test_field_below_the_picker_rows_is_found_through_its_search(picker_context, field, fills):
    # Release b_b17ad783d730 s014: count_distinct of user_id failed "field user_id
    # not in data source" while user_id was in the Data panel, below the picker's rows.
    # Dimensions, metrics, date dimension, breakdown, sort and dropdown fields all
    # pick through _set_fields -> _choose_picker_field.
    from dsengine.ops import charts

    page = Picker(_PICKER)
    charts._choose_picker_field(page, picker_context, field)
    assert (page.fills, page.clicks, page.open) == (fills, [field], False)


@pytest.mark.parametrize("fields, search, fills", [
    (_PICKER, True, ["product_id_str"]),  # searched: "No results", fail at once
    ([], True, []),  # geo picker with no compatible field: "No results" from the start
    (_PICKER, False, []),  # no search box: the rendered rows are all there is
])
def test_field_missing_from_the_picker_fails_without_spending_the_budget(
        picker_context, fields, search, fills):
    from dsengine.ops import OperationError, charts

    page = Picker(fields, search=search)
    with pytest.raises(OperationError, match="^field product_id_str not in data source$"):
        charts._choose_picker_field(page, picker_context, "product_id_str")
    assert (page.fills, page.clicks, page.waits) == (fills, [], 0)


def test_date_control_calendar_is_closed_before_its_resize(tmp_path, monkeypatch):
    # Release b_b17ad783d730 s004 (canvas 1200 x 532): the move's mouse-up opened
    # the control's calendar flush with its bottom edge, the resize corner hit the
    # calendar header, and the control stayed 300 x 50. Retries pressed Escape and
    # moved again (the background's center guide snapped it 2 px), reopening it.
    from types import SimpleNamespace
    from dsengine.ops import charts

    canvas = ScrollingCanvas(532)
    control = Placed(canvas, (24, 24, 300, 50))
    calendar = Nodes(None, [])
    _, events = _scrolling_editor(monkeypatch, canvas, control)
    drag_control = charts._drag

    def drag(page, start, end):
        x, y, w, h = control.box
        if calendar.texts and start[1] - canvas.origin()[1] >= y + h:
            events.append(("hit calendar", start))  # nothing under the corner moves
            return
        drag_control(page, start, end)
        calendar.texts = ["calendar"]  # the mouse-up on the control is a click

    def press(key):
        events.append(("press", key))
        if key == "Escape":
            calendar.texts = []

    def click(x, y):
        events.append(("click", x, y))
        calendar.texts = ["calendar"]

    def locator(selector):
        assert selector == "date_calendar"
        return calendar

    monkeypatch.setattr(charts, "_drag", drag)
    page = SimpleNamespace(mouse=SimpleNamespace(click=click), locator=locator,
                           keyboard=SimpleNamespace(press=press),
                           wait_for_timeout=lambda timeout: None)
    ctx = cleanup_context(tmp_path)
    ctx.selectors = {**ctx.selectors, "date_calendar": "date_calendar"}
    charts._place_chart(page, ctx, control, canvas, (24, 264, 276, 44), dismiss_popup=True)
    assert control.box == (24, 264, 276, 44)
    assert not [event for event in events if event[0] == "hit calendar"], events


# Live scorecard Style tab (2026-10-22, order_items): Labels > Font size offers
# these; Chart title > Font size offers more. A title is its font size + 16 px tall.
_VALUE_SIZES = ["auto", "8px", "9px", "10px", "12px", "14px", "18px", "24px", "28px",
                "30px", "36px", "48px", "60px", "72px", "96px"]
_TITLE_SIZES = ["8px", "9px", "10px", "11px", "12px", "14px", "16px", "18px", "20px",
                "24px", "28px", "30px", "32px", "36px", "40px", "44px", "48px"]


@pytest.mark.parametrize("height, applied", [
    (84, "36px"), (44, "14px"), (60, "30px"), (64, "36px"), (200, "36px"),
    (50, "18px"), (56, "28px"), (20, "14px"),
])
def test_scorecard_value_size_is_the_largest_offered_not_above_the_prototype(height, applied):
    # Release 2.4 b_a8ace098d03b: titled h=84 scorecards showed "10.9M" at 10 px
    # (Labels > Font size "auto"). The prototype uses clamp(16, h - 28, 36) px.
    from dsengine.ops import charts

    assert charts._scorecard_value_size(height, _VALUE_SIZES) == applied
    assert charts._scorecard_value_size(84, ["auto"]) is None


class ScorecardEditor:
    """A scorecard Style tab whose rendered value follows the chosen sizes."""

    def __init__(self, height, titled=True):
        self.height, self.clicks, self.menu, self.titled = height, [], None, titled
        self.value_size, self.title_size, self.hidden, self.padding = "auto", "18px", False, 8

    def fit(self):
        title = int(self.title_size[:-2]) + 16 if self.titled else 0
        value = 10 if self.value_size == "auto" else int(self.value_size[:-2])
        top = title + self.padding + (0 if self.hidden else 8) + 1
        bottom = top + round(value * 1.15)
        return {"size": f"{value}px", "title": self.title_size if self.titled else None,
                "box": [0, top, 100, bottom],
                "over": max(0, bottom - self.height), "wide": False}

    def locator(self, selector):
        page = self

        class Control(Nodes):
            def click(self, *, timeout):
                page.clicks.append(selector)
                if selector == "scorecard_hide_name":
                    page.hidden = not page.hidden
                elif selector != "style_tab":
                    page.menu = selector

            def get_attribute(self, name):
                return "true" if page.hidden else "false"

            def inner_text(self, *, timeout=None):
                return {"scorecard_value_size": page.value_size,
                        "style_title_size": page.title_size}[selector]

        class Option(Nodes):
            def nth(self, index):
                return Option(page, [self.texts[index]])

            def click(self, *, timeout):
                label = self.texts[0]
                page.clicks.append(label)
                if page.menu == "scorecard_value_size":
                    page.value_size = label
                elif page.menu == "style_title_size":
                    page.title_size = label
                else:
                    page.padding = int(label[:-2])
                page.menu = None

        class Pane(Nodes):
            def offered(self):
                return {"scorecard_value_size": _VALUE_SIZES, "style_title_size": _TITLE_SIZES,
                        "scorecard_padding_top": ["0px", "4px", "8px"]}.get(page.menu, [])

            def locator(self, key):
                assert key == "dropdown_option"
                return Nodes(page, self.offered)

            def get_by_text(self, value, *, exact):
                return Option(page, [text for text in self.offered() if text == value])

        return Pane(self, ["pane"]) if selector == "option_overlay" else Control(self, [selector])

    def wait_for_timeout(self, timeout):
        pass


class ScorecardComponent:
    def __init__(self, page):
        self.page = page

    def evaluate(self, expression, selectors, *, timeout):
        assert selectors == ["scorecard_value", "scorecard_title"]
        return self.page.fit()


def _scorecard_context(tmp_path):
    ctx = cleanup_context(tmp_path)
    ctx.events = EventWriter(io.StringIO())
    ctx.selectors = {key: key for key in (
        "style_tab", "scorecard_value_size", "scorecard_hide_name", "scorecard_padding_top",
        "style_title_size", "scorecard_value", "scorecard_title", "option_overlay",
        "dropdown_option")}
    ctx.op_deadline = executor.time.monotonic() + 10  # 5 s stay reserved for verify
    ctx.run_deadline = ctx.op_deadline
    return ctx


@pytest.mark.parametrize("height, title, clicks, message", [
    (84, "Revenue", ["style_tab", "scorecard_value_size", "36px", "scorecard_hide_name",
                     "scorecard_padding_top", "0px"], "s006: scorecard value 36px"),
    # 14px under the 34 px title overflows h=44 by 7 px: the title drops to 11px.
    (44, "Orders", ["style_tab", "scorecard_value_size", "14px", "scorecard_hide_name",
                    "scorecard_padding_top", "0px", "style_title_size", "11px"],
     "s006: scorecard value 14px, title 11px"),
    (84, None, ["style_tab", "scorecard_value_size", "36px"], "s006: scorecard value 36px"),
])
def test_scorecard_value_is_sized_to_its_box_below_the_title(tmp_path, height, title, clicks,
                                                             message):
    from types import SimpleNamespace
    from dsengine.ops import charts

    page, ctx = ScorecardEditor(height, titled=bool(title)), _scorecard_context(tmp_path)
    component = ScorecardComponent(page)
    op = SimpleNamespace(id="s006", chart_type="scorecard", title=title)
    applied = charts._style_scorecard(page, ctx, op, component, height)
    assert page.clicks == clicks
    assert page.hidden is bool(title)
    assert [(e["level"], e["message"]) for e in read_events(ctx.events.stream)] == [("info", message)]
    assert page.fit()["over"] == 0 and applied["fits"]
    charts._verify_scorecard(page, ctx, component, applied)

    page.value_size = "auto"  # Data Studio reverted to its default: verify reads it back
    ctx.op_deadline = executor.time.monotonic() + 0.05
    with pytest.raises(charts.OperationError, match="scorecard_value_size did not read back"):
        charts._verify_scorecard(page, ctx, component, {**applied, "fits": False})


def test_scorecard_value_left_unrendered_by_its_source_warns_within_the_budget(tmp_path):
    # A source error (Data Set Configuration Error) can keep the value from
    # rendering: the chart still succeeds, with the verify reserve left.
    from types import SimpleNamespace
    from dsengine.ops import charts

    page, ctx = ScorecardEditor(44), _scorecard_context(tmp_path)
    ctx.op_deadline = executor.time.monotonic() + 5.3
    component = SimpleNamespace(evaluate=lambda expression, selectors, *, timeout: None)
    op = SimpleNamespace(id="s006", chart_type="scorecard", title="Revenue")
    applied = charts._style_scorecard(page, ctx, op, component, 44)
    assert ctx.remaining_s() > 4.5
    assert (applied["value_size"], applied["hide_name"], applied["fits"]) == ("14px", True, False)
    # The title still drops by the measured rule, without the value's query.
    assert (applied["title_size"], page.title_size, page.fit()["over"]) == ("11px", "11px", 0)
    assert [e["message"] for e in read_events(ctx.events.stream)] == [
        "s006: scorecard value did not render; its fit was not checked",
        "s006: scorecard value 14px, title 11px"]
    charts._verify_scorecard(page, ctx, component, applied)


class FakePagesUI:
    """Manage pages with renamable rows; selector keys double as selectors."""

    def __init__(self, names, active, keep=None):
        self.names, self.active = list(names), active
        self.keep = keep  # Data Studio keeps this name instead of the typed one.
        self.open = False
        self.menu = self.renaming = None
        self.typed = None
        self.calls = []

    def locator(self, key):
        return FakePagesLocator(self, key)


class FakePagesLocator:
    def __init__(self, ui, key, index=None):
        self.ui, self.key, self.index = ui, key, index

    def count(self):
        if self.key == "page_rows":
            return len(self.ui.names) if self.ui.open else 0
        if self.key in {"pages_close", "pages_panel", "page_add"}:
            return int(self.ui.open)
        if self.key == "manage_pages":
            # A one-page report shows Add page in its place; Manage pages is disabled.
            return int(len(self.ui.names) > 1)
        if self.key == "add_page_button":
            return int(len(self.ui.names) == 1 and not self.ui.open)
        if self.key == "page_delete":
            return int(self.ui.menu is not None)
        if self.key == "page_row_menu":
            return int(self.ui.open and self.index < len(self.ui.names))
        return int(self.key in {"canvas", "page_rename", "page_name"})

    def nth(self, index):
        return FakePagesLocator(self.ui, self.key, index)

    def is_visible(self):
        return bool(self.count())

    def locator(self, key):
        return FakePagesLocator(self.ui, key, self.index)

    def inner_text(self):
        if self.key == "manage_pages":
            return f"Page {self.ui.active} of {len(self.ui.names)}"
        assert self.key == "page_rows" and self.ui.open
        return f" {self.ui.names[self.index]} "

    def wait_for(self, *, state, timeout):
        assert self.count()

    def click(self, *, timeout):
        ui = self.ui
        ui.calls.append(("click", self.key, self.index))
        assert self.count(), self.key
        if self.key == "manage_pages":
            ui.open = True
        elif self.key in {"add_page_button", "page_add"}:
            # Add page inserts after the current page and opens the manager.
            ui.names.insert(ui.active, "Untitled Page")
            ui.active += 1
            ui.open = True
        elif self.key == "page_delete":
            del ui.names[ui.menu]
            ui.active = min(ui.active, len(ui.names))
            ui.menu = None
        elif self.key == "pages_close":
            ui.open = False
        elif self.key == "page_row_menu":
            ui.menu = self.index
        elif self.key == "page_rename":
            ui.renaming, ui.menu = ui.menu, None
        elif self.key == "page_rows":
            ui.active = self.index + 1

    def fill(self, value, *, timeout):
        assert self.key == "page_name" and self.ui.renaming is not None
        self.ui.typed = value

    def press(self, key, *, timeout):
        ui = self.ui
        assert (self.key, key) == ("page_name", "Enter")
        ui.names[ui.renaming] = ui.keep if ui.keep is not None else ui.typed
        ui.renaming = None

    def evaluate(self, _expression):
        return [1200, 900]


class FakePagesPage:
    def __init__(self, ui):
        self.ui = ui
        self.keyboard = FakeKeyboard(ui.calls)

    def locator(self, selector):
        return self.ui.locator(selector)

    def wait_for_timeout(self, _ms):
        pass


def pages_context(tmp_path, *ops, seconds=5.0):
    import time

    from dsengine.selectors import load_selectors

    recipe = make_recipe(tmp_path)
    recipe.ops.extend(ops)
    deadline = time.monotonic() + seconds
    selectors = {key: key for key in load_selectors()}
    return OpContext(recipe=recipe, selectors=selectors, events=EventWriter(io.StringIO()),
                     screens=tmp_path, run_deadline=deadline, op_deadline=deadline)


@pytest.mark.parametrize("name", ["Overview", 'Q&A "Top" \'picks\''])
def test_rename_page_on_a_one_page_report_opens_manage_pages_through_a_temporary_page(
        tmp_path, name):
    # Live 2026-10-22: a fresh report has no Manage pages button and Page ->
    # Manage pages is disabled; Add page opens the manager.
    from dsengine.ops import pages

    op = Operation(id="s002", op="rename_page", name=name)
    ui = FakePagesUI(["Untitled Page"], active=1)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op)

    pages.run(page, op, ctx)
    assert ui.open  # verify reads the row before the manager closes
    pages.verify(page, op, ctx)

    assert ui.names == [name] and ui.typed == name
    assert (ui.active, ui.open) == (1, False)
    assert ("click", "add_page_button", None) in ui.calls
    assert ("click", "page_delete", None) in ui.calls
    assert ctx.state["s002"] == {"index": 1, "temporary": False, "name": name}


@pytest.mark.parametrize("left", ["added", "deleted"])
def test_rename_page_retry_deletes_the_temporary_page_once(tmp_path, left):
    from dsengine.ops import pages

    op = Operation(id="s002", op="rename_page", name="Overview")
    ui = FakePagesUI(["Untitled Page"], active=1)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op)
    ctx.state["s002"] = {"index": 1, "temporary": True}
    if left == "added":  # the first attempt failed before deleting it
        ui.names, ui.active, ui.open = ["Untitled Page", "Untitled Page"], 2, True

    pages.run(page, op, ctx)
    pages.verify(page, op, ctx)

    assert ui.names == ["Overview"]
    assert ui.calls.count(("click", "page_delete", None)) == 1


def test_rename_page_verify_fails_when_manage_pages_closed_on_a_one_page_report(tmp_path):
    from dsengine.ops import OperationError, pages

    op = Operation(id="s002", op="rename_page", name="Overview")
    ui = FakePagesUI(["Untitled Page"], active=1)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op)
    pages.run(page, op, ctx)
    ui.open = False

    with pytest.raises(OperationError, match="Manage pages closed"):
        pages.verify(page, op, ctx)


@pytest.mark.parametrize("name", ["Overview", 'Q&A "Top" \'picks\''])
def test_rename_page_renames_the_current_page_through_manage_pages(tmp_path, name):
    from dsengine.ops import handler_for, pages

    op = Operation(id="s002", op="rename_page", name=name)
    ui = FakePagesUI(["Untitled Page", "Detail", "Appendix"], active=2)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op)
    assert handler_for("rename_page") is pages

    pages.run(page, op, ctx)
    pages.verify(page, op, ctx)

    assert ui.names == ["Untitled Page", name, "Appendix"]
    assert ui.typed == name
    assert (ui.active, ui.open) == (2, False)
    assert ctx.state["s002"] == {"index": 2, "name": name}
    assert ("click", "add_page_button", None) not in ui.calls


def test_rename_page_and_add_page_share_one_rename_step(tmp_path, monkeypatch):
    from dsengine.ops import pages

    renamed = []
    original = pages._rename

    def spy(page, ctx, index, name, message):
        renamed.append((index, name))
        return original(page, ctx, index, name, message)

    monkeypatch.setattr(pages, "_rename", spy)
    rename = Operation(id="s002", op="rename_page", name="Overview")
    add = Operation(id="s003", op="add_page", name="Detail")
    ui = FakePagesUI(["Untitled Page"], active=1)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, rename, add)
    for op in (rename, add):
        pages.run(page, op, ctx)
        pages.verify(page, op, ctx)

    assert renamed == [(1, "Overview"), (2, "Detail")]
    assert ui.names == ["Overview", "Detail"]
    assert (ui.active, ui.open) == (2, False)


def test_rename_page_verify_fails_when_the_row_text_differs(tmp_path):
    from dsengine.ops import OperationError, pages

    op = Operation(id="s002", op="rename_page", name="Overview")
    ui = FakePagesUI(["Untitled Page"], active=1)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op)
    pages.run(page, op, ctx)
    ui.names[0] = "Overview (old)"

    with pytest.raises(OperationError, match="page name did not match the recipe"):
        pages.verify(page, op, ctx)
    assert not ui.open


def test_rename_page_fails_within_its_budget_when_the_name_is_not_kept(tmp_path):
    from dsengine.ops import OperationError, pages

    op = Operation(id="s002", op="rename_page", name="Overview")
    ui = FakePagesUI(["Untitled Page"], active=1, keep="Untitled Page")
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op, seconds=0.2)

    with pytest.raises(OperationError, match="page name did not verify"):
        pages.run(page, op, ctx)


def test_rename_page_retry_renames_the_page_current_at_first_attempt(tmp_path):
    from dsengine.ops import pages

    op = Operation(id="s002", op="rename_page", name="Overview")
    ui = FakePagesUI(["Untitled Page", "Detail"], active=1)
    page, ctx = FakePagesPage(ui), pages_context(tmp_path, op)
    ctx.state["s002"] = {"index": 1}
    ui.active = 2  # a failed first attempt left another page current

    pages.run(page, op, ctx)
    pages.verify(page, op, ctx)

    assert ui.names == ["Overview", "Detail"]
    assert ui.active == 1


_PALETTE = ["#2456A6", "#C27D00", "#22B9C7", "#993878"]


_STYLE_SELECTORS = {key: key for key in (
    "style_tab", "style_background", "style_colors", "color_by_position", "series_select",
    "option_overlay", "dropdown_option", "series_color_any", "series_empty_slot", "color_hex",
    "custom_color")}
_STYLE_SELECTORS.update(series_color="seriesColor{n}", series_color_all="seriesColorAll")


def _palette_context(tmp_path, *ops):
    ctx = cleanup_context(tmp_path)
    ctx.events = EventWriter(io.StringIO())
    ctx.recipe.ops = list(ops)
    ctx.selectors = dict(_STYLE_SELECTORS)
    ctx.op_deadline = executor.time.monotonic() + 10
    ctx.run_deadline = ctx.op_deadline
    return ctx


class PaletteEditor:
    """A Style tab with series swatches 0..n-1 that set_color recolors."""

    def __init__(self, swatches):
        self.colors = ["rgb(66, 133, 244)"] * swatches
        self.clicks, self.keyboard = [], FakeKeyboard([])

    def wait_for_timeout(self, timeout):
        pass


def _fake_swatches(monkeypatch, editor):
    from dsengine.ops import style

    def set_color(page, button, color, ctx):
        editor.clicks.append((button, color))
        editor.colors[button] = style.rgb(color)

    monkeypatch.setattr(style, "_swatches", lambda page, ctx, prepare, series=None: (
        (i, i, i == len(editor.colors) - 1) for i in range(len(editor.colors))))
    monkeypatch.setattr(style, "_color_button", lambda control, ctx: control)
    monkeypatch.setattr(style, "_preview", lambda control, ctx: editor.colors[control])
    monkeypatch.setattr(style, "set_color", set_color)
    monkeypatch.setattr(style, "_locator", lambda page, ctx, key: Nodes(editor, [key]))


@pytest.mark.parametrize("swatches, colors, applied", [
    # Release b_a8ace098d03b: a 4-color palette on one-swatch time series and
    # bars, and on a pie's slice swatches.
    (1, _PALETTE, 1), (2, _PALETTE, 2), (9, _PALETTE, 4), (5, _PALETTE[:2], 2), (3, [], 0),
])
def test_colors_apply_to_the_first_min_colors_swatches_in_order(tmp_path, monkeypatch, swatches,
                                                                colors, applied):
    from types import SimpleNamespace
    from dsengine.ops import OperationError, style

    creator = Operation(id="s001", op="add_chart", component_id="chart")
    op = Operation(id="s002", op="set_style", component_id="chart", style={"colors": colors})
    editor, ctx = PaletteEditor(swatches), _palette_context(tmp_path, creator, op)
    component = SimpleNamespace(click=lambda **kwargs: None)
    monkeypatch.setattr(style, "component_for", lambda page, op, ctx: (component, creator))
    _fake_swatches(monkeypatch, editor)

    style.run(editor, op, ctx)

    assert [click for click in editor.clicks if isinstance(click, tuple)] == list(
        enumerate(colors[:applied]))
    assert editor.colors[applied:] == ["rgb(66, 133, 244)"] * (swatches - applied)
    assert ctx.state["s002"]["applied"] == {"colors": colors[:applied]}
    assert [(e["level"], e["message"]) for e in read_events(ctx.events.stream)] == [
        ("info", f"s002: colors applied {applied} of {len(colors)}")]
    style.verify(editor, op, ctx)
    if applied:
        editor.colors[applied - 1] = "rgb(0, 0, 0)"  # verify reads every applied swatch back
        with pytest.raises(OperationError, match="chart series colors did not verify"):
            style.verify(editor, op, ctx)


@pytest.mark.parametrize("creator_op", ["add_chart", "add_text"])
def test_colors_on_a_component_without_series_swatches_skip_with_a_message(
        tmp_path, monkeypatch, creator_op):
    # A scorecard has no series swatch; text has no chart colors at all.
    from types import SimpleNamespace
    from dsengine.ops import style

    creator = Operation(id="s001", op=creator_op, component_id="card")
    op = Operation(id="s002", op="set_style", component_id="card", style={"colors": _PALETTE})
    editor, ctx = PaletteEditor(0), _palette_context(tmp_path, creator, op)
    monkeypatch.setattr(style, "component_for", lambda page, op, ctx: (
        SimpleNamespace(click=lambda **kwargs: None), creator))
    _fake_swatches(monkeypatch, editor)

    style.run(editor, op, ctx)
    style.verify(editor, op, ctx)

    assert ctx.state["s002"]["applied"] == {}
    assert [(e["level"], e["message"]) for e in read_events(ctx.events.stream)] == [
        ("warn", "s002: unsupported style key colors for this component")]


class FakeClock:
    """time.monotonic for the ops: it moves only when the fake editor waits or works."""

    def __init__(self, monkeypatch, now=1000.0):
        self.now = now
        monkeypatch.setattr(executor.time, "monotonic", lambda: self.now)

    def advance(self, seconds):
        self.now += seconds


class SeriesEditor:
    """A time series Style tab: Select metric shows one series' Line color at a time.

    Each wait is a tick (and moves `clock` by its timeout). The option list takes a
    tick to close, the Line color cell follows a pick `lag` ticks after the combobox
    text, picks in `ignore` are lost, and picks in `dead` never show a cell.
    With a breakdown (`series_order` False) Color by shows, and Line colors show only
    once it is Series order (`switches`); with `opens` False the list never opens,
    and until tick `unnamed` it lists empty "Series #n" slots in place of the values.
    """

    def __init__(self, labels, lag=0, ignore=(), *, clock=None, series_order=None,
                 switches=True, opens=True, dead=(), unnamed=0):
        self.labels, self.lag, self.ignore = labels, lag, list(ignore)
        self.clock, self.series_order, self.switches, self.opens = clock, series_order, switches, opens
        self.dead, self.unnamed, self.keyboard = list(dead), unnamed, self
        self.selected = labels[min(1, len(labels) - 1)]
        self.shown, self.pending = self.cell(self.selected), None
        self.open, self.closing, self.tick = False, 0, 0
        self.picks, self.colors = [], {}

    def press(self, key, *, delay=None):
        # Its own keyboard: Escape closes an open option list.
        if key == "Escape" and self.open:
            self.open, self.closing = False, 1

    def listed(self):
        if self.tick >= self.unnamed:
            return list(self.labels)
        return self.labels[:1] + [f"Series #{n}" for n in range(1, len(self.labels))]

    def cell(self, label):
        if label in {"All metrics", "All series"}:
            return "seriesColorAll"
        return f"seriesColor{max(1, self.labels.index(label))}"

    def wait_for_timeout(self, timeout):
        self.tick += 1
        if self.clock:
            self.clock.advance(timeout / 1000)
        self.closing = max(0, self.closing - 1)
        if self.pending and self.tick >= self.pending[0]:
            self.shown, self.pending = self.pending[1], None

    def locator(self, selector):
        return SeriesNode(self, selector)


class SeriesNode:
    def __init__(self, editor, selector, index=0):
        self.editor, self.selector, self.index = editor, selector, index

    def count(self):
        editor = self.editor
        if self.selector == "series_select":
            return 1
        if self.selector == "dropdown_option":
            return len(editor.labels) if editor.open or editor.closing else 0
        if self.selector == "series_empty_slot":
            listed = editor.listed() if editor.open or editor.closing else []
            return sum(bool(re.fullmatch(r"Series #\d+", label)) for label in listed)
        if self.selector == "color_by_position":
            return int(editor.series_order is not None)
        if editor.series_order is False:
            return 0  # Color by Dimension values: no Line color at all
        if self.selector == "series_color_any":
            return int(bool(editor.shown))
        return int(editor.shown == self.selector)  # 0 for style_colors

    def check(self, *, timeout):
        assert self.selector == "color_by_position"
        if self.editor.switches:
            self.editor.series_order = True

    def nth(self, index):
        return SeriesNode(self.editor, self.selector, index)

    @property
    def first(self):
        return self.nth(0)

    def is_visible(self):
        return self.count() > 0

    def locator(self, key):
        assert self.selector == "option_overlay" and key in {"dropdown_option", "series_empty_slot"}
        return SeriesNode(self.editor, key)

    def inner_text(self, *, timeout=None):
        return self.editor.selected + "\t"

    def evaluate_all(self, expression):
        return self.editor.listed()

    def click(self, *, timeout):
        editor = self.editor
        if self.selector == "series_select":
            assert not editor.open and not editor.closing, "reopened a closing option list"
            editor.open = editor.opens
            return
        assert editor.open
        label = editor.labels[self.index]
        editor.picks.append(label)
        editor.open, editor.closing = False, 1
        if label in editor.ignore:
            editor.ignore.remove(label)
            return
        editor.selected = label
        if label in editor.dead:
            editor.shown, editor.pending = None, None
            return
        editor.pending = (editor.tick + editor.lag, editor.cell(label))


@pytest.mark.parametrize("labels, lag, ignore, picks, hint", [
    (["All metrics", "sale_price", "id"], 0, [], ["sale_price", "id"], 2),
    # Live 2026-10-22: the cell followed the combobox text late, and a pick was lost.
    (["All metrics", "sale_price", "id"], 3, ["id"], ["sale_price", "id", "id"], None),
    (["sale_price"], 2, [], ["sale_price"], None),
    # One metric, no breakdown: its Line color shows already, the list stays shut.
    (["sale_price"], 2, [], [], 1),
])
def test_time_series_colors_each_series_line_color_in_select_metric_order(
        tmp_path, monkeypatch, labels, lag, ignore, picks, hint):
    from dsengine.ops import style

    editor, ctx = SeriesEditor(labels, lag, ignore), _palette_context(tmp_path)
    _series_colors(monkeypatch, editor)

    series = len(labels) - (len(labels) > 1)
    assert style._apply_colors(editor, ctx, _PALETTE, hint) == (series, None)
    assert editor.picks == picks
    expected = [style.rgb(c) for c in _PALETTE[:series]]
    assert [editor.colors[f"seriesColor{n}"] for n in range(1, series + 1)] == expected
    assert style._read_colors(editor, ctx, len(_PALETTE), hint) == expected + [None] * (4 - series)


def _series_colors(monkeypatch, editor, seconds=0.0):
    """Color a SeriesEditor's shown Line color; each coloring takes `seconds` of its clock."""
    from dsengine.ops import style

    def set_color(page, button, color, ctx):
        assert editor.shown == button.selector, "colored a Line color that is not shown"
        if editor.clock:
            editor.clock.advance(seconds)
        editor.colors[button.selector] = style.rgb(color)

    monkeypatch.setattr(style, "set_color", set_color)
    monkeypatch.setattr(style, "_color_button", lambda control, ctx: control)
    monkeypatch.setattr(style, "_preview", lambda control, ctx: editor.colors.get(control.selector))


# Release 2.6 b_697880743b4f s010/s011 (live Style tab 2026-10-24): a time series
# by region, six values, then empty slots; the palette has five colors.
_BREAKDOWN = ["All series", "North America", "Asia", "Africa", "South America", "Europe",
              "Oceania", "Series #7", "Series #8", "Series #9", "Series #10"]
_RELEASE_PALETTE = ["#0B2559", "#2B6CB0", "#5A8FD4", "#8FB4E8", "#C8DBF6"]


def test_breakdown_colors_switch_color_by_to_series_order_and_follow_select_series(
        tmp_path, monkeypatch):
    # Color by Dimension values shows no Line color; Series order shows each series'.
    from dsengine.ops import style

    editor, ctx = SeriesEditor(_BREAKDOWN, series_order=False), _palette_context(tmp_path)
    _series_colors(monkeypatch, editor)

    assert style._apply_colors(editor, ctx, _RELEASE_PALETTE) == (5, None)
    assert editor.series_order
    assert editor.picks == _BREAKDOWN[1:6]
    expected = [style.rgb(c) for c in _RELEASE_PALETTE]
    assert [editor.colors.get(f"seriesColor{n}") for n in range(1, 7)] == expected + [None]
    assert style._read_colors(editor, ctx, 5) == expected


def test_breakdown_colors_stop_where_the_op_budget_leaves_verify_its_readback(tmp_path, monkeypatch):
    # The deadline is checked before each series step: a step starts only with
    # time for itself and for verify's readback of every applied series.
    from dsengine.ops import style

    clock = FakeClock(monkeypatch)
    editor, ctx = SeriesEditor(_BREAKDOWN, clock=clock, series_order=True), _palette_context(tmp_path)
    ctx.op_deadline = ctx.run_deadline = clock.now + 12
    _series_colors(monkeypatch, editor, seconds=3)

    assert style._apply_colors(editor, ctx, _RELEASE_PALETTE) == (2, "too little op time left")
    assert editor.picks == _BREAKDOWN[1:3]
    assert ctx.remaining_s() >= style._VERIFY_BASE_S + 2 * style._READBACK_S
    assert style._read_colors(editor, ctx, 2) == [style.rgb(c) for c in _RELEASE_PALETTE[:2]]


_THREE = ["All series", "Complete", "Shipped", "Returned", "Series #4", "Series #5"]


@pytest.mark.parametrize("labels, unnamed, applied", [
    (_THREE, 0, 3),
    # Live 2026-10-24: right after Color by changed, the open list read "Series #1"..
    # "Series #10" and named the values 2.3 s later (here 6 ticks).
    (_THREE, 6, 3),
    # No value is ever named: past the wait, the slots take the colors.
    (["All series", "Series #1", "Series #2"], 0, 2),
])
def test_breakdown_colors_stop_before_the_empty_series_slots(tmp_path, monkeypatch, labels, unnamed,
                                                            applied):
    # Live 2026-10-24: "Series #7".."Series #10" padded six values, and
    # "Series #10" showed no Line color within 2.4 s.
    from dsengine.ops import style

    clock = FakeClock(monkeypatch)
    editor = SeriesEditor(labels, clock=clock, series_order=True, unnamed=unnamed)
    ctx = _palette_context(tmp_path)
    ctx.op_deadline = ctx.run_deadline = clock.now + 20
    _series_colors(monkeypatch, editor)

    assert style._apply_colors(editor, ctx, _RELEASE_PALETTE) == (applied, None)
    assert editor.picks == labels[1:1 + applied]
    expected = [style.rgb(c) for c in _RELEASE_PALETTE[:applied]]
    assert style._read_colors(editor, ctx, len(_RELEASE_PALETTE)) == expected + [None] * (5 - applied)


def test_breakdown_colors_past_the_last_value_are_ignored_not_skipped_for_time(tmp_path, monkeypatch):
    # Live 2026-10-24: six colors on status' five values warned "1 of 6 colors
    # skipped (too little op time left)" though no sixth series existed.
    from dsengine.ops import style

    clock = FakeClock(monkeypatch)
    editor, ctx = SeriesEditor(_THREE, clock=clock, series_order=True), _palette_context(tmp_path)
    ctx.op_deadline = ctx.run_deadline = clock.now + 14
    _series_colors(monkeypatch, editor, seconds=3)

    assert style._apply_colors(editor, ctx, _RELEASE_PALETTE) == (3, None)
    assert ctx.remaining_s() < style._VERIFY_BASE_S + 4 * style._READBACK_S + style._STEP_MIN_S


def test_a_series_without_a_line_color_skips_the_rest_inside_the_op_budget(tmp_path, monkeypatch):
    from dsengine.ops import style

    clock = FakeClock(monkeypatch)
    labels = ["All series", "Complete", "Shipped", "Returned", "Cancelled"]
    editor = SeriesEditor(labels, clock=clock, series_order=True, dead=["Returned"])
    ctx = _palette_context(tmp_path)
    _series_colors(monkeypatch, editor, seconds=1)

    assert style._apply_colors(editor, ctx, _PALETTE) == (2, "series 3 Line color did not show")
    assert editor.picks[:2] == labels[1:3] and set(editor.picks[2:]) == {"Returned"}
    assert ctx.remaining_s() >= style._VERIFY_BASE_S + 2 * style._READBACK_S
    assert not editor.open  # no list left open over later clicks


class BreakdownPage(SeriesEditor):
    """A SeriesEditor as the executor's owned page."""

    mouse = None

    def set_viewport_size(self, _size):
        pass

    def set_default_timeout(self, _timeout):
        pass

    def screenshot(self, *, path, **_kwargs):
        Path(path).write_bytes(b"fake screenshot")

    def close(self):
        pass


@pytest.mark.parametrize("trouble, reason", [
    ({"opens": False}, "series list did not open"),
    ({"switches": False}, "series colors did not appear"),
])
def test_breakdown_colors_without_a_series_list_skip_inside_the_op_budget(
        tmp_path, monkeypatch, trouble, reason):
    # Release 2.6 b_697880743b4f s011 waited all 20 s for swatches a breakdown time
    # series never shows, then timed out on retry (fake clock: waits move it).
    from types import SimpleNamespace
    from dsengine.ops import style

    clock = FakeClock(monkeypatch)
    page = BreakdownPage(_BREAKDOWN, clock=clock, series_order=False, **trouble)
    chart = Operation(id="s002", op="add_chart", component_id="chart", chart_type="time_series",
                      breakdown="region", date_dimension="year", dimensions=[],
                      metrics=[{"field": "people_without_access", "agg": "sum"}])
    recipe = make_recipe(tmp_path)
    recipe.ops = [Operation(id="s001", op="open_report"), chart,
                  Operation(id="s003", op="set_style", component_id="chart",
                            style={"colors": _RELEASE_PALETTE}),
                  Operation(id="s004", op="save_report"), Operation(id="s005", op="get_link")]
    handler = FakeHandler([])

    @contextmanager
    def attach(_config):
        yield FakeBrowserContext(page)

    monkeypatch.setattr(executor, "load_selectors", lambda: dict(_STYLE_SELECTORS))
    monkeypatch.setattr(executor, "build_url", lambda _header: "https://datastudio.google.com/reporting/create?test=1")
    monkeypatch.setattr(executor.chrome, "check", lambda _config: {"signed_in": True})
    monkeypatch.setattr(executor.chrome, "ensure_browser", lambda _config: None)
    monkeypatch.setattr(executor.chrome.ChromeConfig, "from_env",
                        lambda: ChromeConfig(tmp_path / "profile", 9222))
    monkeypatch.setattr(executor.chrome, "attached", attach)
    monkeypatch.setattr(executor, "handler_for", lambda name: style if name == "set_style" else handler)
    monkeypatch.setattr(style, "component_for", lambda page, op, ctx: (
        SimpleNamespace(click=lambda **kwargs: None), chart))
    stream = io.StringIO()

    assert executor.run_recipe(recipe, EventWriter(stream)) == 0

    records = read_events(stream)
    finished = {e["op_id"]: e for e in records if e["event"] == "op_finished"}
    assert (finished["s003"]["status"], finished["s003"]["message"]) == ("ok", "")
    assert finished["s003"]["duration_ms"] < executor.PER_OP_TIMEOUT_S * 1000
    assert [(e["level"], e["message"]) for e in records if e["event"] == "log"] == [
        ("info", "s003: colors applied 0 of 5"), ("warn", f"s003: 5 of 5 colors skipped ({reason})")]
    assert records[-1]["status"] == "ok"


class PieEditor:
    """A pie Style tab: slice swatches appear once Color by is Slice order."""

    def __init__(self):
        self.by_position, self.clicks = False, []

    def wait_for_timeout(self, timeout):
        pass

    def locator(self, selector):
        editor = self

        class Node(Nodes):
            def check(self, *, timeout):
                editor.by_position = True

        if selector == "style_colors":
            return Node(self, lambda: [f"slice{i}" for i in range(9 if self.by_position else 0)])
        return Node(self, [selector] if selector == "color_by_position" else [])


def test_pie_slice_colors_switch_color_by_to_slice_order_first(tmp_path):
    from dsengine.ops import style

    editor, ctx = PieEditor(), _palette_context(tmp_path)
    assert list(style._swatches(editor, ctx, prepare=False)) == []
    assert not editor.by_position  # verify never changes the chart
    found = [(position, control.texts, last)
             for position, control, last in style._swatches(editor, ctx, True)]
    assert editor.by_position
    assert found == [(i, [f"slice{i}"], i == 8) for i in range(9)]


class TypeEditor:
    """A chart dimension chip's field editor: Data type and its two-level menu.

    Live 2026-10-23: the control reads "<type>" then its icon ligature; choosing a
    submenu entry leaves both menus and the editor open until one Escape.
    """

    SUBMENUS = {"date_type_menu": ["Date", "Date & Time", "Year", "Year Quarter", "Year Month",
                                   "ISO Year Week", "Quarter", "Month", "ISO Week"],
                "geo_type_menu": ["Country", "Country subdivision (1st level)", "City"]}

    def __init__(self, data_type="Date", missing=()):
        self.type, self.missing = data_type, set(missing)
        self.editor = self.menu = False
        self.submenu = None
        self.actions = []
        self.keyboard = self

    def press(self, key):
        self.actions.append(("press", key))
        self.editor = self.menu = False
        self.submenu = None

    def wait_for_timeout(self, timeout):
        pass

    def locator(self, selector):
        return TypeNode(self, selector)


class TypeNode:
    def __init__(self, editor, selector, name=None):
        self.editor, self.selector, self.name = editor, selector, name

    @property
    def first(self):
        return self

    def locator(self, selector):
        assert (self.selector, selector) == ("dimension_group_any", "dimension_type_button")
        return TypeNode(self.editor, selector)

    def get_by_role(self, role, *, name, exact):
        assert (self.selector, role, exact) == ("last_overlay", "menuitem", True)
        return TypeNode(self.editor, "menuitem", name)

    def wait_for(self, *, state, timeout):
        assert self.selector == "data_type_control" and state == "visible"
        if not self.editor.editor:
            raise TimeoutError("field editor is closed")

    def inner_text(self):
        assert self.selector == "data_type_control" and self.editor.editor
        return f"{self.editor.type}\narrow_drop_down"

    def hover(self, *, timeout):
        self.editor.actions.append(("hover", self.selector))
        assert self.editor.menu
        self.editor.submenu = [label for label in TypeEditor.SUBMENUS[self.selector]
                               if label not in self.editor.missing]

    def click(self, *, timeout):
        editor = self.editor
        editor.actions.append(("click", self.name or self.selector))
        if self.selector == "dimension_type_button":
            editor.editor = True
        elif self.selector == "data_type_control":
            editor.menu = True
        elif self.name in (editor.submenu or []):
            editor.type = self.name
        else:
            raise TimeoutError(f"menu item {self.name} not found")


def _type_context(tmp_path):
    ctx = cleanup_context(tmp_path)
    ctx.selectors = {key: key for key in (
        "dimension_group_any", "dimension_type_button", "data_type_control", "last_overlay",
        "date_type_menu", "geo_type_menu")}
    return ctx


class Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f"page.{name} used")


@pytest.mark.parametrize("value", ["hour", "Month", "monthly", "", 3, ["month"]])
def test_date_granularity_outside_the_contract_fails_before_any_ui_action(tmp_path, value):
    # Recipe 1.2: day, week, month, quarter or year; checked like geo_type.
    from dsengine.ops import OperationError, charts

    op = _time_series(None, options={"date_granularity": value})
    with pytest.raises(OperationError) as error:
        charts.run(Untouchable(), op, cleanup_context(tmp_path))
    assert str(error.value) == "date_granularity must be day, week, month, quarter or year"


@pytest.mark.parametrize("op", [
    _time_series(None), _time_series(None, options={}),
    _time_series(None, options={"date_granularity": None}),
    _time_series(None, options={"geo_type": "country"}),
    Operation(id="s019", op="add_chart", chart_type="bar", dimensions=["order_date"],
              metrics=[{"field": "revenue", "agg": "sum"}], options={"date_granularity": "x"}),
])
def test_without_date_granularity_the_date_type_is_left_as_inferred(tmp_path, op):
    # Without the option nothing changes: 10.1/11.x replays never open the editor.
    from dsengine.ops import charts

    for change in (True, False):
        charts._date_granularity(Untouchable(), _type_context(tmp_path), op, change=change)


@pytest.mark.parametrize("value, label", [
    ("day", "Date"), ("week", "ISO Year Week"), ("month", "Year Month"),
    ("quarter", "Year Quarter"), ("year", "Year"),
])
def test_date_granularity_sets_the_date_dimension_type_and_reads_it_back(tmp_path, value, label):
    # Release b_36f20b42159c s015: DATE_TRUNC(order_date, MONTH) drew a daily axis
    # with a spike on each 1st; its type in the chart must be Year Month.
    from dsengine.ops import charts

    editor, ctx = TypeEditor(), _type_context(tmp_path)
    op = _time_series(None, options={"date_granularity": value})
    charts._date_granularity(editor, ctx, op, change=True)
    assert editor.type == label
    changed = [("click", "data_type_control"), ("hover", "date_type_menu"), ("click", label)]
    assert editor.actions == [("click", "dimension_type_button"),
                              *(changed if label != "Date" else []), ("press", "Escape")]
    assert not (editor.editor or editor.menu or editor.submenu)

    editor.actions = []
    charts._date_granularity(editor, ctx, op, change=False)
    assert editor.actions == [("click", "dimension_type_button"), ("press", "Escape")]


def test_date_granularity_verify_fails_when_the_type_read_back_differs(tmp_path):
    from dsengine.ops import OperationError, charts

    editor = TypeEditor("Date")
    op = _time_series(None, options={"date_granularity": "month"})
    with pytest.raises(OperationError, match="^time series date dimension type is Date, not Year Month$"):
        charts._date_granularity(editor, _type_context(tmp_path), op, change=False)
    assert editor.actions == [("click", "dimension_type_button"), ("press", "Escape")]
    assert editor.type == "Date"


def test_date_granularity_missing_from_the_menu_closes_the_editor_and_its_menus(tmp_path):
    # An open menu's backdrop intercepts every later click (task 11.3 gotcha).
    from dsengine.ops import charts

    editor = TypeEditor("Date", missing={"Year Month"})
    op = _time_series(None, options={"date_granularity": "month"})
    with pytest.raises(TimeoutError):
        charts._date_granularity(editor, _type_context(tmp_path), op, change=True)
    assert editor.actions[-1] == ("press", "Escape")
    assert not (editor.editor or editor.menu or editor.submenu)


def test_geo_type_and_date_granularity_share_one_data_type_path(tmp_path, monkeypatch):
    from dsengine.ops import charts

    geo = Operation(id="s004", op="add_chart", chart_type="geo_map", dimensions=["country"],
                    metrics=[{"field": "revenue", "agg": "sum"}], options={"geo_type": "region"})
    editor, ctx = TypeEditor("Text"), _type_context(tmp_path)
    charts._geo_type(editor, ctx, geo, change=True)
    # The read-back ignores the icon line, as for the date type.
    assert editor.type == "Country subdivision (1st level)"
    assert editor.actions == [("click", "dimension_type_button"), ("click", "data_type_control"),
                              ("hover", "geo_type_menu"),
                              ("click", "Country subdivision (1st level)"), ("press", "Escape")]

    calls = []
    monkeypatch.setattr(charts, "_data_type", lambda page, ctx, key, label, *, change, subject:
                        calls.append((key, label, change)) or label)
    charts._geo_type(editor, ctx, geo, change=False)
    charts._date_granularity(editor, ctx, _time_series(None, options={"date_granularity": "year"}),
                             change=True)
    assert calls == [("geo_type_menu", "Country subdivision (1st level)", False),
                     ("date_type_menu", "Year", True)]


# Recipe 1.3 (task 13.2): area charts and 100% stacking.
def _area(**options):
    return Operation(id="s002", op="add_chart", component_id="p1_area", chart_type="area",
                     x=24, y=100, w=560, h=280, dimensions=[], date_dimension="created_at",
                     metrics=[{"field": "sale_price", "agg": "sum"}], breakdown="status",
                     options=options)


def _bar(metrics=2, **options):
    return Operation(id="s005", op="add_chart", component_id="p1_split", chart_type="bar",
                     x=24, y=420, w=560, h=280, dimensions=["status"],
                     metrics=[{"field": "sale_price", "agg": "sum"},
                              {"field": "order_id", "agg": "count"}][:metrics],
                     options=options)


@pytest.mark.parametrize("op, stacking, key, variant", [
    (_area(), (False, False), "area_chart", "Area"),
    (_area(stacked=False), (False, False), "area_chart", "Area"),
    (_area(stacked=True), (True, False), "stacked_area_chart", "Stacked area"),
    (_area(stacked_percent=True), (True, True), "percent_stacked_area_chart", "100% stacked area"),
    (_area(stacked=False, stacked_percent=True), (True, True), "percent_stacked_area_chart",
     "100% stacked area"),
    (_bar(), None, "bar_chart", None),
    (_bar(orientation="vertical", stacked=True), (True, False), "stacked_vertical_bar_chart",
     "Stacked bar"),
    (_bar(orientation="horizontal", stacked_percent=True), (True, True),
     "percent_stacked_bar_chart", "100% stacked bar"),
    (_bar(orientation="vertical", stacked_percent=True), (True, True),
     "percent_stacked_vertical_bar_chart", "100% stacked bar"),
    (_bar(stacked_percent=False), (False, False), "bar_chart", "Bar"),
])
def test_area_and_bar_variants_map_to_their_gallery_buttons(op, stacking, key, variant):
    from dsengine.ops import charts
    from dsengine.selectors import load_selectors

    assert charts._stacking(op) == stacking
    assert charts._gallery_key(op, stacking) == key
    assert key in load_selectors()
    if variant:
        assert charts._variant(op, stacking) == variant


@pytest.mark.parametrize("options", [{"stacked_percent": "true"}, {"stacked_percent": 1},
                                     {"stacked": "yes"}, {"stacked_percent": None}])
@pytest.mark.parametrize("make", [_area, _bar])
def test_non_bool_stacking_fails_before_any_ui_action(tmp_path, make, options):
    from dsengine.ops import OperationError, charts

    with pytest.raises(OperationError, match="^stacked and stacked_percent must be true or false$"):
        charts.run(Untouchable(), make(**options), cleanup_context(tmp_path))


def test_area_shares_the_time_series_date_dimension_and_granularity_path(tmp_path, monkeypatch):
    from dsengine.ops import OperationError, charts

    op = _area(date_granularity="month")
    assert charts._dimensions(op) == (["created_at"], [])
    assert charts._granularity(op) == "month"
    calls = []
    monkeypatch.setattr(charts, "_data_type", lambda page, ctx, key, label, *, change, subject:
                        calls.append((key, label, change, subject)) or "Date")
    with pytest.raises(OperationError, match="^area date dimension type is Date, not Year Month$"):
        charts._date_granularity(Untouchable(), _type_context(tmp_path), op, change=False)
    assert calls == [("date_type_menu", "Year Month", False, "area date dimension")]
    for value in ("hour", 3):
        with pytest.raises(OperationError, match="^date_granularity must be"):
            charts.run(Untouchable(), _area(date_granularity=value), cleanup_context(tmp_path))


class StackSwitch:
    def __init__(self, ui, key):
        self.ui, self.key = ui, key

    def count(self):
        return 1

    def nth(self, index):
        return self

    def is_visible(self):
        return self.key in self.ui.shown

    def wait_for(self, *, state, timeout):
        assert self.is_visible()

    def get_attribute(self, name):
        assert name == "aria-checked"
        return "true" if self.ui.on.get(self.key) else "false"

    def click(self, *, timeout):
        self.ui.clicks.append(self.key)
        self.ui.on[self.key] = not self.ui.on.get(self.key)
        if self.key != "percent_stack_switch":
            # 100% stacking shows only while stacked (live 2026-10-24).
            (self.ui.shown.add if self.ui.on[self.key] else self.ui.shown.discard)(
                "percent_stack_switch")


class StackUI:
    def __init__(self, stack_key, stacked, percent, *, hidden=False):
        self.on = {stack_key: stacked, "percent_stack_switch": percent}
        self.shown = set() if hidden else {stack_key} | ({"percent_stack_switch"} if stacked else set())
        self.clicks = []

    def locator(self, selector):
        return StackSwitch(self, selector)


def _stack_context(tmp_path):
    ctx = cleanup_context(tmp_path)
    ctx.events = EventWriter(io.StringIO())
    ctx.selectors = {key: key for key in ("stacked_switch", "area_stack_switch",
                                          "percent_stack_switch")}
    return ctx


@pytest.mark.parametrize("op, found", [
    (_area(), (False, False)), (_area(stacked=True), (True, False)),
    (_area(stacked_percent=True), (True, True)), (_bar(stacked_percent=True), (True, True)),
    (_bar(stacked=True), (True, False)),
])
def test_stacking_is_read_back_from_the_style_switches_and_logged(tmp_path, op, found):
    from dsengine.ops import charts

    ctx = _stack_context(tmp_path)
    key = "stacked_switch" if op.chart_type == "bar" else "area_stack_switch"
    assert charts._read_stacking(StackUI(key, *found), ctx, op) == found
    charts._verify_stacking(StackUI(key, *found), ctx, op, found)
    log = read_events(ctx.events.stream)[-1]
    assert (log["level"], log["message"]) == ("info", f"{op.id}: {charts._variant(op, found)}")


def test_stacking_switches_are_set_in_order_and_only_while_shown(tmp_path):
    from dsengine.ops import charts

    ctx = _stack_context(tmp_path)
    ui = StackUI("area_stack_switch", False, False)
    charts._set_stacking(ui, ctx, _area(stacked_percent=True), (True, True))
    assert ui.clicks == ["area_stack_switch", "percent_stack_switch"]
    assert charts._read_stacking(ui, ctx, _area()) == (True, True)

    ui = StackUI("stacked_switch", True, True)
    charts._set_stacking(ui, ctx, _bar(stacked=False), (False, False))
    assert ui.clicks == ["stacked_switch"]  # 100% stacking hides once unstacked
    assert charts._read_stacking(ui, ctx, _bar()) == (False, False)


def test_one_series_hides_stacking_and_reads_back_as_unknown(tmp_path):
    from dsengine.ops import charts

    ctx = _stack_context(tmp_path)
    ui = StackUI("stacked_switch", False, False, hidden=True)
    single = _bar(metrics=1, stacked_percent=True)
    charts._set_stacking(ui, ctx, single, (True, True))
    assert ui.clicks == []
    assert charts._read_stacking(ui, ctx, single) is None
    charts._verify_stacking(ui, ctx, single, (True, True))
    assert read_events(ctx.events.stream)[-1]["message"] == (
        "s005: 100% stacked bar (one series: stacking not shown)")
    # Two series always show the switch: hidden reads as unstacked, not unknown.
    assert charts._read_stacking(ui, ctx, _bar(stacked_percent=True)) == (False, False)


@pytest.mark.parametrize("op, shown, message", [
    (_area(stacked_percent=True), (True, False), "area variant read back Stacked area, not 100% stacked area"),
    (_area(), (True, True), "area variant read back 100% stacked area, not Area"),
    (_bar(stacked_percent=True), (False, False), "bar variant read back Bar, not 100% stacked bar"),
])
def test_verify_fails_when_the_variant_reads_back_differently(tmp_path, op, shown, message):
    from dsengine.ops import OperationError, charts

    key = "stacked_switch" if op.chart_type == "bar" else "area_stack_switch"
    with pytest.raises(OperationError, match=f"^{re.escape(message)}$"):
        charts._verify_stacking(StackUI(key, *shown), _stack_context(tmp_path), op,
                                charts._stacking(op))


class ControlUI:
    """One field control: an insert menu, a canvas, and Style's two list-mode radios."""

    def __init__(self, inserted):
        self.inserted, self.count, self.calls = inserted, 0, []
        self.keyboard = self

    def press(self, key):
        self.calls.append(("press", key))

    def node(self, key):
        from types import SimpleNamespace

        ui = self

        class Node:
            def click(self, timeout=None):
                ui.calls.append(("click", key))

            def wait_for(self, state, timeout=None):
                ui.calls.append(("wait", key, state))

            def count(self):
                return ui.count if key == "components" else 1

            def nth(self, index):
                return SimpleNamespace(locator=lambda selector: SimpleNamespace(count=lambda: 1))

            def is_checked(self):
                ui.calls.append(("read", key))
                return key == ui.inserted

            def bounding_box(self):
                return {"x": 0, "y": 0, "width": 1200, "height": 900}

        return Node()


def _control_editor(monkeypatch, tmp_path, inserted):
    from dsengine.ops import controls

    ui = ControlUI(inserted)
    target = (24, 100, 200, 220)

    def click_canvas(page, ctx, canvas, x, y):
        ui.count += 1

    def poll(page, ctx, ready, message):
        assert ready(), message

    def set_fields(page, ctx, group, fields):
        ui.calls.append(("fields", fields))

    for name, value in {
        "_locator": lambda page, ctx, key: ui.node(key),
        "_source_fields": lambda page, ctx: [], "_require_source_field": lambda *a: None,
        "_chart_box": lambda op, ctx: (target, False), "_wait_visible": lambda *a: None,
        "_click_canvas": click_canvas, "_poll": poll, "_set_fields": set_fields,
        "_place_chart": lambda page, ctx, comp, canvas, box, dismiss_popup: ui.calls.append(
            ("place", box)),
        "_geometry": lambda component: target, "_field_names": lambda group, ctx: ["status"],
    }.items():
        monkeypatch.setattr(controls, name, value)
    ctx = cleanup_context(tmp_path)
    ctx.selectors = {**ctx.selectors, "component_dropdown_control": "filter",
                     "component_fixed_size_list_control": "filter"}
    return controls, ui, ctx


def _control_op(control_type, **extra):
    return Operation(id="s002", op="add_control", component_id="p1_region",
                     control_type=control_type, x=24, y=100, w=200, h=220, **extra)


@pytest.mark.parametrize("control_type, menu, mode", [
    ("dropdown", "dropdown_control", "control_mode_dropdown"),
    ("fixed_size_list", "fixed_size_list_control", "control_mode_fixed_size_list"),
])
def test_field_controls_share_one_path_and_read_their_list_mode_back(
        tmp_path, monkeypatch, control_type, menu, mode):
    # Recipe 1.3 (release 2.6 region list): Fixed-size list is the drop-down's
    # dimension-filter; only the insert menu entry and Style > expandable differ.
    controls, ui, ctx = _control_editor(monkeypatch, tmp_path, inserted=mode)
    op = _control_op(control_type, field="status")
    controls.run(ui, op, ctx)
    assert ui.calls == [("click", "add_control"), ("click", menu), ("wait", menu, "hidden"),
                        ("place", (24, 100, 200, 220)), ("press", "Escape"),
                        ("click", "setup_tab"), ("fields", ["status"])]
    ui.calls.clear()
    controls.verify(ui, op, ctx)
    assert ui.calls == [("click", "style_tab"), ("read", mode), ("click", "setup_tab")]


@pytest.mark.parametrize("control_type, other", [
    ("dropdown", "control_mode_fixed_size_list"),
    ("fixed_size_list", "control_mode_dropdown"),
])
def test_field_control_of_the_other_list_mode_fails_verify(tmp_path, monkeypatch, control_type, other):
    from dsengine.ops import OperationError

    controls, ui, ctx = _control_editor(monkeypatch, tmp_path, inserted=other)
    op = _control_op(control_type, field="status")
    controls.run(ui, op, ctx)
    with pytest.raises(OperationError, match="^inserted control type did not match the recipe$"):
        controls.verify(ui, op, ctx)


def test_fixed_size_list_without_a_field_fails_before_any_click(tmp_path, monkeypatch):
    from dsengine.ops import OperationError

    controls, ui, ctx = _control_editor(monkeypatch, tmp_path, inserted=None)
    with pytest.raises(OperationError, match="^fixed_size_list requires a field$"):
        controls.run(ui, _control_op("fixed_size_list"), ctx)
    assert ui.calls == []
