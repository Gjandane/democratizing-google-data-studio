"""Golden compiler-order recipe, real run budget, and timeout recovery."""

import base64
import json
import os
import re
import shutil
import statistics
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import load_dotenv
from jsonschema import Draft202012Validator, FormatChecker
from playwright.sync_api import expect

from dsengine import chrome
from dsengine.cli import main
from dsengine.ops.charts import _geometry
from dsengine.recipe import ENGINE_ROOT, load_recipe
from dsengine.selectors import load_selectors

pytestmark = pytest.mark.live
FIXTURES = Path(__file__).parent / "recipes"


def _recipe(tmp_path):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    records = [json.loads(line) for line in (FIXTURES / "golden.jsonl").read_text().splitlines()]
    # Keep the fixture's supported subset in the shared compiler's order.
    sample = [json.loads(line) for line in (
        ENGINE_ROOT.parent / "contracts/fixtures/recipe.sample.jsonl"
    ).read_text().splitlines()][1:]
    supported = {"open_report", "set_canvas", "set_background_image", "add_chart",
                 "save_report", "get_link"}
    expected = [(op["op"], op.get("chart_type")) for op in sample
                if op["op"] in supported]
    # The golden recipe needs one scorecard, rather than the sample's two.
    expected.remove(("add_chart", "scorecard"))
    assert [(op["op"], op.get("chart_type")) for op in records[1:]] == expected
    project, dataset, table = os.environ.get(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    records[0]["datasource"].update(project_id=project, dataset_id=dataset, table_id=table)
    records[0]["build_id"] = f"b_{uuid.uuid4().hex[:12]}"
    records[0]["report_name"] += " " + records[0]["build_id"]
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    shutil.copyfile(FIXTURES / "background_p1.png", tmp_path / "background_p1.png")
    load_recipe(path)  # Validate the actual recipe passed to the CLI.
    return path, records[1:]


def _open_saved(url, ops, tmp_path, *, complete):
    parsed = urlsplit(url)
    assert parsed.hostname in {"datastudio.google.com", "lookerstudio.google.com"}
    assert "/reporting/" in parsed.path and "/create" not in parsed.path
    assert not parsed.path.endswith("/edit")
    selectors = load_selectors()
    with chrome.attached(chrome.ChromeConfig.from_env()) as context:
        page = context.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(url, wait_until="domcontentloaded")
            expect(page.locator(selectors["canvas"])).to_be_visible(timeout=20000)
            if complete:
                images = page.locator(selectors["image_component"])
                expect(images).to_have_count(1, timeout=20000)
                expect(page.locator(selectors["image_content"])).to_be_visible()
                assert _geometry(images) == (0, 0, 1200, 900)
                assert page.locator(selectors["image_content"]).evaluate("e => e.naturalWidth") == 1200
                components = page.locator(selectors["components"])
                assert components.first.locator(selectors["image_content"]).count() == 1
                charts = page.locator(selectors["chart_components"]).filter(
                    has_not=page.locator(selectors["image_content"])
                )
                chart_ops = [op for op in ops if op["op"] == "add_chart"]
                expect(charts).to_have_count(len(chart_ops), timeout=20000)
                for index, op in enumerate(chart_ops):
                    chart = charts.nth(index)
                    assert all(abs(actual - op[key]) <= 4 for actual, key in zip(
                        _geometry(chart), ("x", "y", "w", "h")
                    ))
                    expect(chart).to_contain_text(op["title"], timeout=20000)
                    if op["chart_type"] in {"time_series", "bar", "pie"}:
                        frame = chart.locator(selectors["chart_iframe"])
                        expect(frame).to_have_count(1, timeout=20000)
                        expect(frame.content_frame.locator(selectors["chart_frame_body"])).to_contain_text(
                            re.compile(r"\d"), timeout=20000
                        )
                    else:
                        expect(chart).to_contain_text(op["metrics"][0]["field"], timeout=20000)
            page.screenshot(path=str(tmp_path / "saved_report.png"), full_page=True)
        finally:
            page.close()


@pytest.mark.parametrize("timeout,screencast", [(300, False), (30, False), (300, True)],
                         ids=["budget", "timeout-recovery", "screencast"])
def test_golden_recipe(tmp_path, capsys, timeout, screencast):
    recipe, ops = _recipe(tmp_path)
    started = time.monotonic()
    args = ["run", str(recipe), "--timeout", str(timeout),
            "--screens", str(tmp_path / "screens")]
    if screencast:
        args.append("--screencast")
    code = main(args)
    elapsed = time.monotonic() - started
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out, encoding="utf-8")
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [event for event in events if event["event"] == "op_finished"]
    result = events[-1]
    schema = json.loads((ENGINE_ROOT.parent / "contracts/recipe.schema.json").read_text())
    validator = Draft202012Validator(
        {"$ref": "#/$defs/event", "$defs": schema["$defs"]}, format_checker=FormatChecker())
    for event in events:
        validator.validate(event)
    frames = [index for index, event in enumerate(events) if event["event"] == "frame"]
    if screencast:
        assert frames, "live screencast emitted no frames"
        first_start = next(i for i, e in enumerate(events) if e["event"] == "op_started")
        last_finish = max(i for i, e in enumerate(events) if e["event"] == "op_finished")
        assert any(first_start < index < last_finish for index in frames)
        for index in frames:
            assert base64.b64decode(events[index]["data"], validate=True).startswith(b"\xff\xd8")
    else:
        assert not frames
    (tmp_path / "budget.json").write_text(json.dumps({
        "elapsed_s": elapsed,
        "median_op_s": statistics.median(event["duration_ms"] for event in finished) / 1000,
        "schema_valid_events": len(events),
        "jpeg_frames": len(frames),
        "result": result,
    }, indent=2), encoding="utf-8")
    assert output.err == "", output.err
    assert [event["op_id"] for event in finished] == [op["id"] for op in ops], output.out
    assert [event["op_id"] for event in events if event["event"] == "op_started"] == [
        op["id"] for op in ops
    ]
    assert result["event"] == "run_finished"
    assert result["report_url"], output.out
    assert [event["status"] for event in finished[-2:]] == ["ok", "ok"], output.out
    if timeout == 300:
        assert code == 0, output.out
        assert result["error_code"] is None, output.out
        assert result["ok"] / len(ops) >= 0.9, output.out
        assert elapsed < 300
        assert statistics.median(event["duration_ms"] for event in finished) <= 15000
    else:
        assert code == 1, output.out
        assert result["status"] == "failed"
        assert result["error_code"] == "timeout", output.out
        assert elapsed >= 30
        assert any(event["status"] != "ok" for event in finished[:-2]), output.out
    _open_saved(result["report_url"], ops, tmp_path, complete=timeout == 300)
