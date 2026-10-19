"""Live acceptance for text, images, component styles and page operations."""

import json
import os
import shutil
import statistics
import time
import traceback
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from playwright.sync_api import expect

from dsengine import chrome
from dsengine.cli import main
from dsengine.events import EventWriter
from dsengine.ops import OpContext, OperationError, pages, style, text
from dsengine.ops.charts import _geometry
from dsengine.recipe import ENGINE_ROOT, load_recipe
from dsengine.selectors import load_selectors

pytestmark = pytest.mark.live
FIXTURES = Path(__file__).parent / "recipes"


def _recipe(tmp_path):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    records = [json.loads(s) for s in (FIXTURES / "misc.jsonl").read_text().splitlines()]
    project, dataset, table = os.getenv(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    records[0]["datasource"].update(project_id=project, dataset_id=dataset, table_id=table)
    records[0]["build_id"] = "b_" + uuid.uuid4().hex[:12]
    records[0]["report_name"] += " " + records[0]["build_id"]
    path = tmp_path / "misc.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    shutil.copyfile(FIXTURES / "background_p1.png", tmp_path / "background_p1.png")
    return load_recipe(path)


def test_misc_ops(tmp_path, capsys, monkeypatch):
    recipe = _recipe(tmp_path)
    diagnostics = []
    # Prove the executor's retry reuses text/image/page creations.
    attempts = {}
    for module in (text, pages, style):
        original = module.run

        def observed(page, op, ctx, original=original):
            try:
                result = original(page, op, ctx)
                if op.id in {"s002", "s003", "s006"}:
                    attempts[op.id] = attempts.get(op.id, 0) + 1
                    if attempts[op.id] == 1:
                        raise OperationError("injected transient failure after creation")
                return result
            except Exception:
                diagnostics.append(traceback.format_exc())
                raise

        monkeypatch.setattr(module, "run", observed)
    started = time.monotonic()
    code = main(["run", str(recipe.path), "--screens", str(tmp_path / "screens")])
    elapsed = time.monotonic() - started
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out)
    (tmp_path / "diagnostics.txt").write_text("\n".join(diagnostics))
    events = [json.loads(s) for s in output.out.splitlines()]
    finished = [e for e in events if e["event"] == "op_finished"]
    (tmp_path / "budget.json").write_text(json.dumps({
        "total_ops": len(recipe.ops), "elapsed_s": elapsed,
        "median_op_s": statistics.median(e["duration_ms"] for e in finished) / 1000,
        "summed_op_s": sum(e["duration_ms"] for e in finished) / 1000,
    }, indent=2), encoding="utf-8")
    assert code == 0 and not output.err, output.out + output.err
    assert [e["op_id"] for e in finished] == [op.id for op in recipe.ops]
    assert all(e["status"] == "ok" for e in finished), (finished, diagnostics)
    assert attempts == {"s002": 2, "s003": 2, "s006": 2}
    assert any(e["event"] == "log" and e["level"] == "warn"
               and "unsupported_example" in e["message"] for e in events)
    assert events[-1]["status"] == "ok" and events[-1]["report_url"]
    assert len(recipe.ops) == 20 and elapsed < 300
    assert statistics.median(e["duration_ms"] for e in finished) <= 15000
    assert sum(e["duration_ms"] for e in finished) < 300000
    selectors = load_selectors()
    with chrome.attached(chrome.ChromeConfig.from_env()) as browser:
        page = browser.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(events[-1]["report_url"] + "/edit", wait_until="domcontentloaded")
            expect(page.locator(selectors["manage_pages"])).to_contain_text("of 3", timeout=20000)
            ctx = OpContext(recipe, selectors, EventWriter(), tmp_path, time.monotonic() + 120)
            ctx.op_deadline = time.monotonic() + 20
            pages.switch(page, ctx, 1)
            components = page.locator(selectors["components"])
            expect(components).to_have_count(3, timeout=20000)
            for component, op in zip(components.all(), recipe.ops[1:4]):
                assert all(abs(a - op.model_extra[k]) <= 4 for a, k in zip(
                    _geometry(component), ("x", "y", "w", "h")))
            viewer = components.nth(0).locator(selectors["text_viewer"])
            expect(viewer).to_have_text(recipe.ops[1].text, use_inner_text=True)
            rendered = text.text_styles(components.nth(0), ctx)
            assert rendered and all(s == {"size": 30, "color": style.rgb("#123456"),
                                         "bold": True, "align": "center"} for s in rendered)
            image = components.nth(1).locator(selectors["image_content"])
            expect(image).to_be_visible()
            expect(image).to_have_js_property("naturalWidth", 1200, timeout=20000)
            components.nth(2).click(position={"x": 10, "y": 10})
            page.locator(selectors["style_tab"]).click()
            for key, values in [("style_colors", ["#2468AC", "#C86428"]),
                                ("style_background", ["#F0F4F8"]),
                                ("style_border_color", ["#456789"])]:
                controls = page.locator(selectors[key])
                assert controls.count() == len(values)
                assert [style._preview(c, ctx) for c in controls.all()] == [style.rgb(v) for v in values]
            expect(page.locator(selectors["style_title_size"])).to_have_text("24px")
            expect(page.locator(selectors["show_title_switch"])).to_be_checked()
            page.keyboard.press("Escape")
            expect(page.locator(selectors["loading"])).to_have_count(0, timeout=20000)
            page.screenshot(path=str(tmp_path / "page1.png"), full_page=True)
            ctx.op_deadline = time.monotonic() + 20
            pages.switch(page, ctx, 2)
            expect(components).to_have_count(1, timeout=20000)
            expect(components.first).to_contain_text("Second page")
            rendered = text.text_styles(components.first, ctx)
            assert rendered and all(s == {"size": 26, "color": style.rgb("#2468AC"),
                                         "bold": False, "align": "right"} for s in rendered)
            page.locator(selectors["manage_pages"]).click()
            rows = page.locator(selectors["pages_panel"]).locator(selectors["page_rows"])
            expect(rows.nth(1)).to_have_text("Details")
            page.screenshot(path=str(tmp_path / "page2.png"), full_page=True)
            ctx.op_deadline = time.monotonic() + 20
            pages.switch(page, ctx, 3)
            expect(components).to_have_count(2, timeout=20000)
            assert text.text_content(components.first, ctx) == "\n"
            expect(components.nth(1).locator(selectors["image_content"])).to_have_js_property(
                "naturalWidth", 1200, timeout=20000)
            creators = {op.component_id: op for op in recipe.ops
                        if op.op in {"add_text", "add_image"}}
            for component, key in zip(components.all(), ("p3_blank", "p3_image")):
                expected = creators[key]
                assert all(abs(actual - getattr(expected, field)) <= 4
                           for actual, field in zip(_geometry(component), ("x", "y", "w", "h")))
            page.screenshot(path=str(tmp_path / "page3.png"), full_page=True)
        finally:
            page.close()
