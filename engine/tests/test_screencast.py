"""CDP frame contract, throttling, ownership and executor lifecycle."""

import base64
import io
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from playwright.sync_api import Error as PlaywrightError

from dsengine import chrome, executor
from dsengine.events import EventWriter
from dsengine.recipe import ENGINE_ROOT
from test_executor import (
    fake_driver, install_handler, make_recipe, read_events,
)


class FakeCDP:
    def __init__(self, fail=None):
        self.listeners = {}
        self.calls = []
        self.detached = False
        self.fail = fail

    def on(self, name, callback):
        self.listeners[name] = callback

    def remove_listener(self, name, callback):
        assert self.listeners.pop(name) == callback

    def send(self, name, params=None):
        self.calls.append((name, params))
        if name == self.fail:
            raise PlaywrightError("fake CDP failure")

    def detach(self):
        self.detached = True

    def frame(self, number):
        callback = self.listeners.get("Page.screencastFrame")
        if callback:
            callback({"sessionId": number, "data": base64.b64encode(
                b"\xff\xd8frame\xff\xd9" + bytes([number])
            ).decode()})


def owned_page(session):
    page = SimpleNamespace()

    def new_session(target):
        assert target is page
        return session

    page.context = SimpleNamespace(new_cdp_session=new_session)
    return page


def test_frames_schema_rate_and_acknowledgements(monkeypatch):
    session = FakeCDP()
    stream = io.StringIO()
    now = [0.0]
    monkeypatch.setattr(chrome.time, "monotonic", lambda: now[0])
    capture = chrome.Screencast(owned_page(session), EventWriter(stream))
    emitted_at = []
    for number, instant in enumerate([0, .1, .399, .4, .499, .5, .9, 1., 1.499, 1.5]):
        now[0] = instant
        before = len(stream.getvalue())
        session.frame(number)
        if len(stream.getvalue()) != before:
            emitted_at.append(instant)
    assert emitted_at == [0, .5, 1., 1.5]
    assert all(b - a >= .4 for a, b in zip(emitted_at, emitted_at[1:]))
    schema = json.loads((ENGINE_ROOT.parent / "contracts/recipe.schema.json").read_text())
    validator = Draft202012Validator(
        {"$ref": "#/$defs/event", "$defs": schema["$defs"]},
        format_checker=FormatChecker(),
    )
    for record in read_events(stream):
        validator.validate(record)
        assert record["event"] == "frame"
        assert base64.b64decode(record["data"]).startswith(b"\xff\xd8")
    assert [params["sessionId"] for name, params in session.calls
            if name == "Page.screencastFrameAck"] == list(range(10))
    capture.close()
    before = stream.getvalue()
    session.frame(20)
    assert stream.getvalue() == before
    assert session.detached and not session.listeners
    assert session.calls[0] == ("Page.startScreencast", {"format": "jpeg", "quality": 60})
    assert session.calls[-1][0] == "Page.stopScreencast"


@pytest.mark.parametrize("failure", ["Page.startScreencast", "Page.stopScreencast"])
def test_session_detached_on_start_or_stop_failure(failure):
    session = FakeCDP(fail=failure)
    if failure == "Page.startScreencast":
        with pytest.raises(PlaywrightError):
            chrome.Screencast(owned_page(session), EventWriter(io.StringIO()))
    else:
        chrome.Screencast(owned_page(session), EventWriter(io.StringIO())).close()
    assert session.detached and not session.listeners


@pytest.mark.parametrize("enabled,dry_run,open_fails", [
    (True, False, False), (False, False, False),
    (True, True, False), (True, False, True),
])
def test_executor_capture_lifecycle(fake_driver, monkeypatch, tmp_path,
                                    enabled, dry_run, open_fails):
    page, calls, events, stream = fake_driver
    session = FakeCDP()
    page.context = owned_page(session).context
    # Assert CDP attaches to the executor-owned page, not the helper page.
    page.context.new_cdp_session = lambda target: session if target is page else pytest.fail("foreign tab")
    install_handler(monkeypatch, calls, fail_run={"s001": 2} if open_fails else {})
    original = executor._run_one

    def run_one(*args):
        session.frame(1)
        return original(*args)

    monkeypatch.setattr(executor, "_run_one", run_one)
    recipe = make_recipe(tmp_path, "open_report", "save_report", "get_link")
    assert executor.run_recipe(recipe, events, screencast=enabled, dry_run=dry_run) == (
        1 if open_fails and not dry_run else 0
    )
    records = read_events(stream)
    frames = [i for i, row in enumerate(records) if row["event"] == "frame"]
    assert bool(frames) == (enabled and not dry_run)
    if frames:
        assert records[frames[0] - 1]["event"] == "op_started"
        assert records[frames[0] + 1]["event"] == "op_finished"
        assert session.detached and not session.listeners
    else:
        assert not session.calls
    assert records[-1]["event"] == "run_finished"
    assert page.closed == (not dry_run)
