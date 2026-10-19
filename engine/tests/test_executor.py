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
        self.raise_after_upload = False

    def locator(self, selector):
        if selector in {"components", "chart_components"}:
            return ImageCollection(self, charts=selector == "chart_components")
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


class ImageAction:
    def __init__(self, page, key):
        self.page, self.key = page, key

    def click(self, *, timeout):
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
        "send_back", "image_content", "canvas")}, EventWriter(io.StringIO()), tmp_path,
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
    monkeypatch.setattr(report, "_place_component", lambda _page, component, canvas, box:
                        setattr(component, "box", box))
    original_locator = report._locator
    monkeypatch.setattr(report, "_locator", lambda p, c, key:
                        object() if key == "canvas" else original_locator(p, c, key))
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
    from dsengine.ops import report

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

    monkeypatch.setattr(report, "_drag", drag)
    page = SimpleNamespace(mouse=FakeMouse(calls))
    report._place_component(page, component, canvas, (1100, 800, 100, 100))
    assert drags == [((533, 350), (300, 200)), ((250, 150), (1350, 950))]
    assert component.box == (1100, 800, 100, 100)
