"""Live replays of compiled-recipe op sequences that failed in release builds."""

import json
import os
import shutil
import struct
import traceback
import uuid
import zlib
from pathlib import Path

import pytest
from dotenv import load_dotenv

from dsengine.cli import main
from dsengine.ops import charts, controls, report, text
from dsengine.recipe import ENGINE_ROOT

pytestmark = pytest.mark.live

RECIPES = Path(__file__).parent / "recipes"


def _labels(page, ctx, key):
    return charts._field_names(ctx.locator(page, key), ctx)


def _matches(actual, expected):
    return len(actual) == len(expected) and all(
        charts._matches_field(label, field) for label, field in zip(actual, expected)
    )


def _write_png(path, width, height):
    # A plain RGB PNG at the backend's per_section size, without an image dependency.
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + bytes((80, 65, 146) if y % 200 < 8 else (236, 238, 248)) * width
                    for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _replay(name, tmp_path, capsys, monkeypatch):
    """Run a recipe fixture on DSS_TEST_TABLE and read boxes and Setup fields back per op."""
    load_dotenv(ENGINE_ROOT.parent / ".env")
    project, dataset, table = os.environ.get(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    records = [json.loads(line) for line in
               (RECIPES / name).read_text(encoding="utf-8").splitlines()]
    header = records[0]
    header["build_id"] = f"b_{uuid.uuid4().hex[:12]}"
    header["report_name"] = f"{header['report_name']} {header['build_id']}"
    header["datasource"].update(project_id=project, dataset_id=dataset, table_id=table)
    recipe_path = tmp_path / name
    recipe_path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")

    readback = {}
    diagnostics = []
    chart_verify, control_verify = charts.verify, controls.verify
    report_verify, text_verify = report.verify, text.verify

    # Read Setup fields and boxes back independently of the production
    # verifier, right after it passes, while the component is still selected.
    def read_chart(page, op, ctx):
        chart_verify(page, op, ctx)
        state = ctx.state[op.id]
        component = ctx.locator(page, "chart_components").nth(state["chart_index"])
        ctx.locator(page, "setup_tab").click()
        readback[op.id] = {
            "box": charts._geometry(component),
            "dimensions": _labels(page, ctx, "dimension_group_any") if state["dimensions"] else [],
            "metrics": _labels(page, ctx, "metric_group_any"),
            "sort": _labels(page, ctx, "sort_group") if state["sort"] else [],
        }

    def read_control(page, op, ctx):
        control_verify(page, op, ctx)
        state = ctx.state[op.id]
        component = ctx.locator(page, "components").nth(state["control_index"])
        readback[op.id] = {
            "box": charts._geometry(component),
            "field": _labels(page, ctx, "control_field_group") if state["field"] else [],
        }

    def read_text(page, op, ctx):
        text_verify(page, op, ctx)
        component = ctx.locator(page, "components").nth(ctx.state[op.id]["component_index"])
        readback[op.id] = {"box": charts._geometry(component)}

    def read_report(page, op, ctx):
        report_verify(page, op, ctx)
        if op.op == "set_background_image":
            component = ctx.state[op.id]["component"]
            readback[op.id] = {
                "box": report._geometry(component),
                "paint_index": report._component_index(ctx.locator(page, "components"), component),
                "selected": charts._visible(ctx.locator(page, "selected_component")),
            }

    def observed(run):
        def wrapper(page, op, ctx):
            try:
                return run(page, op, ctx)
            except Exception:
                diagnostics.append(f"{op.id}\n{traceback.format_exc()}")
                raise
        return wrapper

    monkeypatch.setattr(charts, "verify", read_chart)
    monkeypatch.setattr(controls, "verify", read_control)
    monkeypatch.setattr(text, "verify", read_text)
    monkeypatch.setattr(report, "verify", read_report)
    for module in (charts, controls, text, report):
        monkeypatch.setattr(module, "run", observed(module.run))

    code = main(["run", str(recipe_path), "--screens", str(tmp_path / "screens")])
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out, encoding="utf-8")
    (tmp_path / "diagnostics.txt").write_text("\n".join(diagnostics), encoding="utf-8")
    (tmp_path / "readback.json").write_text(json.dumps(readback, indent=2), encoding="utf-8")
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [event for event in events if event["event"] == "op_finished"]
    statuses = [(event["op_id"], event["status"], event["message"]) for event in finished]
    assert code == 0, (statuses, diagnostics)
    assert [status for _, status, _ in statuses] == ["ok"] * (len(records) - 1), (statuses, diagnostics)
    assert (events[-1]["event"], events[-1]["status"], events[-1]["failed"]) == ("run_finished", "ok", 0)
    return records[1:], readback


def _assert_readback(ops, readback):
    """Boxes within 4 px in canvas coordinates; chart and control Setup fields as recipe."""
    for op in ops:
        if op["op"] == "add_chart":
            found = readback[op["id"]]
            dimensions = ([op["date_dimension"]] if op.get("date_dimension") else []) + op["dimensions"]
            metrics = [metric["field"] for metric in op["metrics"]]
            assert _matches(found["dimensions"], dimensions), (op["id"], found)
            assert _matches(found["metrics"], metrics), (op["id"], found)
            assert "Record Count" not in found["metrics"], (op["id"], found)
            if op.get("sort") and op["chart_type"] == "time_series":
                # No Sort section exists: the date dimension read back first
                # (asserted above) is the order; the fixture must ask for it.
                assert (op["sort"]["field"], op["sort"]["order"]) == (dimensions[0], "asc")
            elif op.get("sort"):
                assert any(charts._matches_field(label, op["sort"]["field"])
                           for label in found["sort"]), (op["id"], found)
        elif op["op"] == "add_control":
            found = readback[op["id"]]
            assert _matches(found["field"], [op["field"]] if op.get("field") else []), (op["id"], found)
        elif op["op"] in {"add_text", "set_background_image"}:
            found = readback[op["id"]]
        else:
            continue
        expected = (op["x"], op["y"], op["w"], op["h"])
        assert all(abs(a - e) <= 4 for a, e in zip(found["box"], expected)), (op["id"], found)
    placed = {"add_chart", "add_control", "add_text", "set_background_image"}
    assert len(readback) == sum(op["op"] in placed for op in ops)


def test_compiled_recipe_sequence_sets_every_field(tmp_path, capsys, monkeypatch):
    shutil.copy(RECIPES / "background_p1.png", tmp_path / "background_p1.png")
    ops, readback = _replay("recipe_replay.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)


def test_tall_canvas_places_every_component_below_the_fold(tmp_path, capsys, monkeypatch):
    # Release b_b2ac19ea6696 page 3 (1200 x 1492): the background stayed at its
    # upload position, the table kept its default width and the bar timed out.
    _write_png(tmp_path / "background_tall.png", 1200, 1492)
    ops, readback = _replay("tall_canvas.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)
    background = readback["s004"]
    assert background["paint_index"] == 0, background
    assert background["selected"] is False, background
    below = {op["op"] for op in ops if op.get("y", 0) >= 1200}
    assert below == {"add_chart", "add_control", "add_text"}
