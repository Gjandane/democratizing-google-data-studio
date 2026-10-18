import asyncio
import copy
import json
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from dss.config import Config
from dss.main import create_app
from dss.recipe.compiler import compile_recipe
from dss.render.prototype import render
from dss.spec.layout import box
from dss.spec.models import DashboardSpec, Cell
from fakes import fake_models

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT.parent / "contracts/recipe.schema.json").read_text())

@pytest.fixture
def thin(monkeypatch, tmp_path):
    monkeypatch.setenv("DSS_DEV", "1")
    monkeypatch.setenv("DSS_ENGINE_CMD", f'"{sys.executable}" "{ROOT / "tests/fake_engine.py"}"')
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "1")
    app = create_app(Config(data_dir=tmp_path), model_lister=fake_models)
    with TestClient(app) as client:
        build = client.post("/api/builds", json={"title":"Sales", "archetype":"executive", "mode":"data"}).json()
        yield client, app, build["id"], tmp_path / "builds" / build["id"] / "v1"


def load(client, bid):
    result = client.post(f"/api/dev/builds/{bid}/load-spec")
    assert result.status_code == 200, result.text
    assert result.json()["stage"] == "prototype"


def wait_done(client, bid):
    for _ in range(300):
        build = client.get(f"/api/builds/{bid}").json()
        if build["stage"] != "build":
            return build
        time.sleep(.02)
    pytest.fail("Engine did not finish")

class Items(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.items = []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-cid" in attrs:
            self.items.append(attrs)


def test_flow(thin):
    client, app, bid, folder = thin
    load(client, bid)
    spec = DashboardSpec.model_validate_json((folder / "spec.json").read_text())
    html = client.get(f"/api/builds/{bid}/prototype").text
    explicit = client.get(f"/api/builds/{bid}/prototype?layer=all")
    assert explicit.status_code == 200
    assert explicit.text == html
    items = Items(html).items
    expected = spec.pages[0].decorations + spec.pages[0].components
    assert len(items) == len(expected)
    assert {i["data-cid"] for i in items} == {i.id for i in expected}
    for item, actual in zip(expected, items):
        b = box(spec.canvas, spec.grid, item.grid)
        for key, css in (("x","left"),("y","top"),("w","width"),("h","height")):
            assert f'{css}:{b[key]}px' in actual["style"]
        assert actual["data-label"]
        assert actual["data-kind"] in ("component", "decoration")
    layer = Items(client.get(f"/api/builds/{bid}/prototype?layer=decoration").text).items
    assert all("display:none" in i["style"] for i in layer if i["data-kind"] == "component")
    response = client.post(f"/api/builds/{bid}/recipe")
    assert response.status_code == 200, response.text
    recipe = [json.loads(l) for l in (folder / "recipe.jsonl").read_text().splitlines()]
    for i, line in enumerate(recipe):
        Draft202012Validator({**SCHEMA, "$ref":"#/$defs/header" if i == 0 else "#/$defs/op"}).validate(line)
    assert response.json()["op_count"] == len(recipe)-1
    assert [i["op_id"] for i in response.json()["ops"]] == [i["id"] for i in recipe[1:]]
    # Subscribe to the very same bus consumed by the SSE route before accepting the run.
    async def observe():
        async with app.state.bus.subscribe(bid) as queue:
            response = await asyncio.to_thread(client.post, f"/api/builds/{bid}/run")
            assert response.status_code == 202
            events = []
            while True:
                event = await asyncio.wait_for(queue.get(), 10)
                events.append(event)
                if event["event"] == "build.finished":
                    return events, response.json()["run_id"]
    events, run_id = client.portal.call(observe)
    assert len([e for e in events if e["event"] == "build.op"]) == len(recipe)-1
    assert json.loads(events[-1]["data"]) == {"status":"ok", "report_url":None, "version":1}
    assert wait_done(client, bid)["stage"] == "done"
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM traces WHERE run_id=?", (run_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM traces WHERE build_id=?", (bid,)).fetchone()[0] == 4
    assert (folder / "events.jsonl").is_file()


def test_layout_and_determinism():
    spec = DashboardSpec.model_validate_json((ROOT / "tests/data/thin_spec.json").read_text())
    import random
    rng = random.Random(123)
    for _ in range(100):
        spec.canvas.width = rng.randint(700, 1800)
        left = box(spec.canvas, spec.grid, Cell(col=1,row=1,w=6,h=2))
        right = box(spec.canvas, spec.grid, Cell(col=7,row=1,w=6,h=2))
        assert left["x"] == 24
        assert 15 <= right["x"] - left["x"] - left["w"] <= 17
        assert right["x"] + right["w"] == spec.canvas.width - 24
    with pytest.raises(ValueError):
        box(spec.canvas, spec.grid, Cell(col=12,row=1,w=2,h=2))
    with pytest.raises(ValueError):
        box(spec.canvas, spec.grid, Cell(col=1,row=50,w=2,h=2))
    a = compile_recipe(spec, 1)
    assert a == compile_recipe(spec, 1)
    ops = [json.loads(l) for l in a.splitlines()[1:]]
    assert [o["id"] for o in ops] == [f"s{i:03d}" for i in range(1,len(ops)+1)]
    assert [o["op"] for o in ops] == ["open_report","set_canvas","set_background_image","add_chart","set_style","add_chart","set_style","add_text","save_report","get_link"]
    assert [o["component_id"] for o in ops if o["op"] == "set_style"] == ["p1_revenue","p1_regions"]
    assert json.loads(a.splitlines()[0])["datasource"]["table_id"] == "small_sales"
    spec.pages[0].components[0].label = '<script>"bad"</script>'
    assert '<script>' not in render(spec)


def test_dev_off_and_wrong_stage(monkeypatch, tmp_path):
    monkeypatch.setenv("DSS_DEV", "0")
    with TestClient(create_app(Config(data_dir=tmp_path), model_lister=fake_models)) as client:
        assert client.post('/api/dev/builds/b_123456789abc/load-spec').status_code == 404


def test_missing_and_busy(thin, monkeypatch):
    client, app, bid, folder = thin
    assert client.get('/api/builds/b_000000000000/prototype').status_code == 404
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 409
    load(client, bid)
    assert client.post(f'/api/builds/{bid}/run').status_code == 409
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    monkeypatch.setenv("DSS_ENGINE_CMD", f'"{sys.executable}" "{ROOT / "tests/fake_engine.py"}"')
    app.state.engine_busy = True
    assert client.post(f'/api/builds/{bid}/run').json()["error"]["code"] == "engine_busy"
    app.state.engine_busy = False

@pytest.mark.parametrize("flag,stage,status", [("--broken","prototype","failed"),("--partial","done","partial")])
def test_failure_and_partial(thin, monkeypatch, flag, stage, status):
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    # Mode flag goes after the recipe positional argument.
    original = __import__('dss.harness.nodes.execute', fromlist=['engine_command'])
    real_popen = original.subprocess.Popen
    def popen(args, **kwargs):
        return real_popen([*args, flag], **kwargs)
    monkeypatch.setattr(original.subprocess, 'Popen', popen)
    assert client.post(f'/api/builds/{bid}/run').status_code == 202
    assert wait_done(client, bid)["stage"] == stage
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT status FROM versions WHERE build_id=?", (bid,)).fetchone()[0] == status


def test_all_recipe_mappings():
    spec = DashboardSpec.model_validate_json((ROOT / "tests/data/thin_spec.json").read_text())
    template = spec.pages[0].components[0].model_dump()
    from dss.spec.models import Component, TYPES
    spec.pages[0].components = []
    for kind in TYPES:
        data = {**template, "id": "p1_" + kind, "type": kind, "text": "A note", "image_path": "logo.png", "field": "region"}
        spec.pages[0].components.append(Component.model_validate(data))
    lines = [json.loads(line) for line in compile_recipe(spec, 3).splitlines()]
    for i, line in enumerate(lines):
        Draft202012Validator({**SCHEMA, "$ref": "#/$defs/header" if i == 0 else "#/$defs/op"}).validate(line)
    assert lines[0]["version"] == 3
    creations = [op for op in lines[1:] if op["op"].startswith("add_")]
    assert len(creations) == len(TYPES)
    for kind, op in zip(TYPES, creations):
        expected = "add_control" if kind in ("date_range", "dropdown") else "add_text" if kind == "text" else "add_image" if kind == "image" else "add_chart"
        assert op["op"] == expected
        if expected == "add_chart":
            assert op["chart_type"] == kind
    assert len([op for op in lines if op.get("op") == "set_style"]) == 8


def test_wrapper_timeout_releases_engine(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    monkeypatch.setenv("DSS_ENGINE_CMD", f'uv run --no-sync python "{ROOT / "tests/fake_engine.py"}"')
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "1")
    monkeypatch.setenv("DSS_FAKE_HANG", "1")
    started = time.monotonic()
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    deadline = started + 15
    while time.monotonic() < deadline:
        build = client.get(f"/api/builds/{bid}").json()
        if build["stage"] == "prototype" and not app.state.engine_busy:
            break
        time.sleep(.05)
    assert build["stage"] == "prototype"
    assert build["versions"][0]["status"] == "failed"
    assert not app.state.engine_busy
    assert time.monotonic() - started < 15
    # A second run can acquire the lock and finish normally.
    monkeypatch.delenv("DSS_FAKE_HANG")
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    assert wait_done(client, bid)["stage"] == "done"


def test_cancel_terminates_engine_tree(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    monkeypatch.setenv("DSS_FAKE_HANG", "1")
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "60")
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    deadline = time.monotonic() + 5
    while not (folder / "fake-child-started").exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert (folder / "fake-child-started").exists()
    async def cancel():
        task = next(iter(app.state.engine_tasks))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), 5)
    client.portal.call(cancel)
    assert not app.state.engine_busy
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "prototype"
