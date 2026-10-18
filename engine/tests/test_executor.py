import io
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

import dsengine.executor as executor
from dsengine.events import EventWriter
from dsengine.ops import OpResult
from dsengine.recipe import Canvas, Datasource, Header, Operation, Recipe


class FakeKeyboard:
    def press(self, *_args, **_kwargs):
        pass


class FakePage:
    def __init__(self):
        self.keyboard = FakeKeyboard()
        self.closed = False

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
    page = FakePage()
    calls = []
    monkeypatch.setattr(executor, "load_selectors", lambda: {"canvas": "fake"})
    monkeypatch.setattr(executor, "build_url", lambda _header: "https://datastudio.google.com/reporting/create?test=1")
    monkeypatch.setattr(executor.chrome, "check", lambda _config: {"signed_in": True})
    monkeypatch.setattr(executor.chrome.ChromeConfig, "from_env", lambda: "fake-config")

    @contextmanager
    def attach(_config):
        yield FakeBrowserContext(page)

    monkeypatch.setattr(executor.chrome, "attached", attach)
    monkeypatch.setattr(executor, "reset_ui", lambda *_args: calls.append(("reset",)))
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
    assert calls.count(("reset",)) == 1
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


def test_empty_recipe_succeeds_without_browser(fake_driver, monkeypatch, tmp_path):
    _page, calls, events, stream = fake_driver
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
