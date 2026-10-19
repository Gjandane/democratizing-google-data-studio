import json
import os
import struct
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from dsengine.cli import main

pytestmark = pytest.mark.live


def _png(path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack("!I", len(data)) + kind + data
                + struct.pack("!I", zlib.crc32(kind + data)))

    pixels = (b"\0" + b"\xe8\xef\xf7" * 1200) * 900
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 1200, 900, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def test_five_report_operations_save_a_view_link(tmp_path, capsys):
    table = os.environ.get("DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items")
    project, dataset, table_name = table.split(".")
    build_id = f"b_{uuid.uuid4().hex[:12]}"
    background = tmp_path / "background.png"
    _png(background)
    recipe_path = tmp_path / "recipe.jsonl"
    header = {
        "recipe_version": "1.0",
        "build_id": build_id,
        "version": 1,
        "report_name": f"Engine report ops {build_id}",
        "canvas": {"width": 1200, "height": 900},
        "datasource": {
            "connector": "bigQuery",
            "project_id": project,
            "dataset_id": dataset,
            "table_id": table_name,
        },
    }
    ops = [
        {"id": "s001", "op": "open_report"},
        {"id": "s002", "op": "set_canvas", "width": 1200, "height": 900},
        {"id": "s003", "op": "set_background_image", "path": background.name,
         "x": 0, "y": 0, "w": 1200, "h": 900},
        {"id": "s004", "op": "save_report"},
        {"id": "s005", "op": "get_link"},
    ]
    recipe_path.write_text(
        "\n".join(json.dumps(record) for record in [header, *ops]) + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(recipe_path), "--screens", str(tmp_path / "screens")])

    output = capsys.readouterr()
    assert exit_code == 0, output.err
    assert output.err == ""
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [event for event in events if event["event"] == "op_finished"]
    assert len(finished) == 5
    assert [event["status"] for event in finished] == ["ok"] * 5, [
        (event["op_id"], event["status"], event["message"]) for event in finished
    ]
    run_finished = events[-1]
    assert run_finished["event"] == "run_finished"
    assert run_finished["status"] == "ok"
    assert (run_finished["ok"], run_finished["failed"], run_finished["skipped"]) == (5, 0, 0)
    parsed = urlsplit(run_finished["report_url"])
    assert parsed.hostname in {"datastudio.google.com", "lookerstudio.google.com"}
    assert "/reporting/" in parsed.path
    assert "/create" not in parsed.path
    assert not parsed.path.endswith("/edit")


def test_backgrounds_reuse_upload_and_preserve_component_identity(tmp_path, capsys, monkeypatch):
    import time
    import traceback
    from playwright.sync_api import expect
    from dsengine import chrome
    from dsengine.events import EventWriter
    from dsengine.ops import OpContext, OperationError, report, text
    from dsengine.recipe import load_recipe
    from dsengine.selectors import load_selectors

    background = tmp_path / "background.png"
    _png(background)
    project, dataset, table = os.environ.get(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items").split(".")
    header = {
        "recipe_version": "1.0", "build_id": "b_" + uuid.uuid4().hex[:12],
        "version": 1, "report_name": "Background identity regression " + uuid.uuid4().hex[:8],
        "canvas": {"width": 1200, "height": 900},
        "datasource": {"connector": "bigQuery", "project_id": project,
                       "dataset_id": dataset, "table_id": table},
    }
    ops = [
        {"id": "s001", "op": "open_report"},
        {"id": "s002", "op": "add_image", "component_id": "ordinary", "path": background.name,
         "x": 500, "y": 100, "w": 180, "h": 180},
        {"id": "s003", "op": "add_text", "component_id": "first", "text": "First target",
         "x": 30, "y": 30, "w": 240, "h": 70, "font_size": 18},
        {"id": "s004", "op": "add_text", "component_id": "second", "text": "Second unchanged",
         "x": 30, "y": 220, "w": 240, "h": 70, "font_size": 20},
        {"id": "s005", "op": "set_background_image", "path": background.name,
         "x": 0, "y": 0, "w": 400, "h": 400},
        {"id": "s006", "op": "set_background_image", "path": background.name,
         "x": 1100, "y": 800, "w": 400, "h": 400},
        {"id": "s007", "op": "set_style", "component_id": "first", "style": {"font_size": 30}},
        {"id": "s008", "op": "save_report"},
        {"id": "s009", "op": "get_link"},
    ]
    recipe_path = tmp_path / "backgrounds.jsonl"
    recipe_path.write_text("\n".join(json.dumps(r) for r in [header, *ops]) + "\n")
    attempts, diagnostics, counts = [], [], []
    prepare = report._prepare_image

    def transient(page, component, ctx):
        if ctx.current_op == "set_background_image" and "s006" not in ctx.state:
            counts.append(page.locator(ctx.selectors["components"]).count())
            attempts.append(ctx.state["s005"]["component"])
            if len(attempts) == 1:
                raise OperationError("injected transient failure after upload")
        return prepare(page, component, ctx)

    monkeypatch.setattr(report, "_prepare_image", transient)
    original = report.run
    original_text = text.run

    def observed_text(page, op, ctx):
        try:
            return original_text(page, op, ctx)
        except Exception:
            diagnostics.append(traceback.format_exc())
            raise

    monkeypatch.setattr(text, "run", observed_text)

    def observed(page, op, ctx):
        try:
            return original(page, op, ctx)
        except Exception:
            diagnostics.append(traceback.format_exc())
            raise

    monkeypatch.setattr(report, "run", observed)
    code = main(["run", str(recipe_path), "--screens", str(tmp_path / "screens")])
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out)
    (tmp_path / "diagnostics.txt").write_text("\n".join(diagnostics))
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [e for e in events if e["event"] == "op_finished"]
    assert code == 0 and not output.err, output.out + output.err
    assert all(e["status"] == "ok" for e in finished), (finished, diagnostics)
    assert len(finished) == len(ops)
    assert events[-1]["status"] == "ok"
    assert counts == [4, 4]
    assert len(attempts) == 2 and attempts[0] is attempts[1]
    assert any(e["event"] == "log" and "clamped" in e["message"] for e in events)
    selectors = load_selectors()
    with chrome.attached(chrome.ChromeConfig.from_env()) as browser:
        page = browser.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(events[-1]["report_url"], wait_until="domcontentloaded")
            components = page.locator(selectors["components"])
            expect(components).to_have_count(5, timeout=20000)
            expected_boxes = [(1100, 800, 100, 100), (0, 0, 400, 400),
                              (500, 100, 180, 180), (30, 30, 240, 70), (30, 220, 240, 70)]
            ctx = OpContext(load_recipe(recipe_path), selectors, EventWriter(), tmp_path,
                            time.monotonic() + 60)
            for index, box in enumerate(expected_boxes):
                component = components.nth(index)
                assert all(abs(a - e) <= 4 for a, e in zip(report._geometry(component), box))
                if index < 3:
                    image = component.locator(selectors["image_content"])
                    expect(image).to_be_visible()
                    expect(image).to_have_js_property("naturalWidth", 1200, timeout=20000)
                else:
                    assert text.text_content(component, ctx) == ops[index - 1]["text"]
                    styles = text.text_styles(component, ctx)
                    assert styles and all(s["size"] == (30 if index == 3 else 20) for s in styles)
            page.screenshot(path=str(tmp_path / "backgrounds_saved.png"), full_page=True)
        finally:
            page.close()
