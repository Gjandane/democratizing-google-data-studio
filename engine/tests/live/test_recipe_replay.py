"""Live replays of compiled-recipe op sequences that failed in release builds."""

import json
import os
import re
import shutil
import struct
import traceback
import uuid
import zlib
from pathlib import Path

import pytest
from dotenv import load_dotenv
from playwright.sync_api import expect

from dsengine import chrome
from dsengine.cli import main
from dsengine.ops import charts, controls, report, style, text
from dsengine.recipe import ENGINE_ROOT
from dsengine.selectors import load_selectors

pytestmark = pytest.mark.live

RECIPES = Path(__file__).parent / "recipes"


def _labels(page, ctx, key):
    return charts._field_names(ctx.locator(page, key), ctx)


def _matches(actual, expected):
    return len(actual) == len(expected) and all(
        charts._matches_field(label, field) for label, field in zip(actual, expected)
    )


_VALUE = """(component, [valueKey, titleKey, nameKey]) => {
    const value = component.querySelector(valueKey), title = component.querySelector(titleKey);
    if (!value || !value.innerText.trim()) return null;
    const box = r => [r.left, r.top, r.right, r.bottom].map(Math.round);
    const label = component.querySelector(nameKey);
    return {font_size: getComputedStyle(value).fontSize, text: value.innerText.trim(),
            value: box(value.getBoundingClientRect()),
            component: box(component.getBoundingClientRect()),
            title: title && box(title.getBoundingClientRect()),
            name_shown: !!label && getComputedStyle(label).display !== 'none'};
}"""


def _scorecard_value(page, ctx, component):
    """The rendered value's computed font size and boxes, once its query returns."""
    keys = [ctx.selectors[key] for key in ("scorecard_value", "scorecard_title", "scorecard_name")]
    for _ in range(40):
        found = component.evaluate(_VALUE, keys)
        if found:
            return found
        page.wait_for_timeout(250)
    return None


def _date_type(page, ctx):
    """The date dimension chip's Data type, read in its field editor."""
    ctx.locator(page, "dimension_group_any").locator(
        ctx.selectors["dimension_type_button"]).first.click()
    control = ctx.locator(page, "data_type_control")
    control.wait_for(state="visible")
    found = control.inner_text().splitlines()[0].strip()
    page.keyboard.press("Escape")
    return found


_MONTH = re.compile(r"[A-Z][a-z]{2} \d{4}")  # "Jan 2019"; days read "Jan 6, 2019" or "Jan 1"
_AXIS = "(body, key) => [...body.querySelectorAll(key)].map(e => e.textContent.trim()).filter(Boolean)"


def _x_axis_labels(page, ctx, component):
    """The rendered x-axis labels, once they are all months or the op budget runs low."""
    body = component.frame_locator(ctx.selectors["chart_iframe"]).locator(
        ctx.selectors["chart_frame_body"])
    found = []
    while ctx.remaining_s() > 3:  # leave the op's own cleanup some budget
        try:
            found = body.evaluate(_AXIS, ctx.selectors["chart_x_axis_label"], timeout=1000)
        except Exception:
            found = []  # the chart iframe is created lazily
        if found and all(_MONTH.fullmatch(label) for label in found):
            break
        page.wait_for_timeout(250)
    return found


def _write_png(path, width, height):
    # A plain RGB PNG at the backend's per_section size, without an image dependency.
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + bytes((80, 65, 146) if y % 200 < 8 else (236, 238, 248)) * width
                    for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _replay(name, tmp_path, capsys, monkeypatch, own_source=False):
    """Run a recipe fixture on DSS_TEST_TABLE (own_source: on the table its header names)
    and read boxes and Setup fields back per op."""
    load_dotenv(ENGINE_ROOT.parent / ".env")
    project, dataset, table = os.environ.get(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    records = [json.loads(line) for line in
               (RECIPES / name).read_text(encoding="utf-8").splitlines()]
    header = records[0]
    header["build_id"] = f"b_{uuid.uuid4().hex[:12]}"
    header["report_name"] = f"{header['report_name']} {header['build_id']}"
    if not own_source:
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
        if op.chart_type == "scorecard":
            readback[op.id]["value"] = _scorecard_value(page, ctx, component)
            if readback[op.id]["value"] is None:
                page.screenshot(path=str(tmp_path / f"{op.id}_unrendered.png"))
                readback[op.id]["shown"] = component.inner_text()
        if "rows_per_page" in (getattr(op, "options", None) or {}):
            readback[op.id]["rows_per_page"] = (
                ctx.locator(page, "rows_per_page_control").inner_text().strip())
        if "date_granularity" in (getattr(op, "options", None) or {}):
            readback[op.id]["date_type"] = _date_type(page, ctx)
            readback[op.id]["x_axis"] = _x_axis_labels(page, ctx, component)

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
    for module in (charts, controls, text, report, style):
        monkeypatch.setattr(module, "run", observed(module.run))
    monkeypatch.setattr(style, "verify", observed(style.verify))

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


def test_manual_acceptance_fields_date_control_and_rows_per_page(tmp_path, capsys, monkeypatch):
    # Release 2.4 b_b17ad783d730 page 1 (1200 x 532): the date_range calendar
    # covered the resize corner, and user_id was below the picker's rendered
    # rows. b_568901c19819: Rows per page offers no 15. order_items has fewer
    # columns than the release view, so the scorecard's picker renders user_id;
    # s007's sixth metric is where its own metrics push user_id out of the rows.
    _write_png(tmp_path / "background_short.png", 1200, 532)
    ops, readback = _replay("acceptance_fixes.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)
    assert readback["s008"]["rows_per_page"] == "10", readback["s008"]
    events = [json.loads(line) for line in
              (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    warnings = [event["message"] for event in events
                if event["event"] == "log" and event["level"] == "warn"]
    assert "s008: rows_per_page 15 is not offered; applied 10" in warnings, warnings


def test_scorecard_values_are_sized_to_their_boxes_below_the_title(tmp_path, capsys, monkeypatch):
    # Release 2.4 b_a8ace098d03b page 1: titled h=84 scorecards drew "10.9M" at
    # 10 px under a 5 px metric name (Labels > Font size "auto"). The rule is
    # clamp(16, h - 28, 36) px, Data Studio's largest offered size not above it.
    ops, readback = _replay("scorecards.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)
    expected = {84: "36px", 44: "14px"}
    for op in ops:
        if op["op"] != "add_chart":
            continue
        found = readback[op["id"]]["value"]
        assert found and found["font_size"] == expected[op["h"]], (op["id"], found)
        left, top, right, bottom = found["value"]
        c_left, c_top, c_right, c_bottom = found["component"]
        assert c_left <= left and right <= c_right and c_top <= top and bottom <= c_bottom, (
            op["id"], found)
        assert found["title"] and found["title"][3] <= top, (op["id"], found)
        assert not found["name_shown"], (op["id"], found)
    events = [json.loads(line) for line in
              (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    infos = [event["message"] for event in events
             if event["event"] == "log" and event["level"] == "info"]
    assert "s003: scorecard value 36px" in infos, infos
    assert any(message.startswith("s005: scorecard value 14px") for message in infos), infos


_LEGEND = """(body, symbol) => [...body.querySelectorAll(symbol)].map(e => getComputedStyle(e).fill)"""


def _legend_colors(page, ctx, component, expected):
    """The rendered legend symbols' fills, once their first colors are the expected ones."""
    body = component.frame_locator(ctx.selectors["chart_iframe"]).locator(
        ctx.selectors["chart_frame_body"])
    found = None
    while ctx.remaining_s() > 3:  # leave the op's own cleanup some budget
        try:
            found = body.evaluate(_LEGEND, ctx.selectors["chart_legend_symbol"],
                                  timeout=ctx.timeout_ms())
        except Exception:
            found = None
        if found and found[:len(expected)] == expected:
            break
        page.wait_for_timeout(250)
    return found


def test_series_swatches_take_the_palette_in_order(tmp_path, capsys, monkeypatch):
    # Release 2.4 b_a8ace098d03b: all 16 `set_style colors` were skipped as
    # unsupported, since the 4-color palette was longer than every chart's
    # swatch list. Colors apply to the first min(len(colors), swatches).
    palette = ["#2456A6", "#C27D00", "#22B9C7", "#993878"]
    expected = {"s004": 1, "s006": 1, "s008": 4}
    rendered = {}
    style_verify = style.verify

    def read_style(page, op, ctx):
        style_verify(page, op, ctx)
        if op.id in expected:
            component, _ = style.component_for(page, op, ctx)
            rendered[op.id] = _legend_colors(
                page, ctx, component, [style.rgb(c) for c in palette[:expected[op.id]]])
        elif op.id == "s013":
            # Two daily series can render "Too Many Rows" on order_items, with no
            # legend (and slow the ops after it: it sits alone on page 2): read
            # both Line colors back from Select metric instead.
            rendered[op.id] = style._read_colors(page, ctx, len(palette))

    monkeypatch.setattr(style, "verify", read_style)
    ops, readback = _replay("colors.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)
    (tmp_path / "rendered.json").write_text(json.dumps(rendered, indent=2), encoding="utf-8")
    for op_id, count in expected.items():
        assert rendered[op_id] and rendered[op_id][:count] == [
            style.rgb(c) for c in palette[:count]], (op_id, rendered)
    # The pie has five status slices: the fifth keeps Data Studio's color.
    assert len(rendered["s008"]) == 5 and rendered["s008"][4] not in map(style.rgb, palette), rendered
    assert rendered["s013"] == [style.rgb(c) for c in palette[:2]] + [None, None], rendered
    events = [json.loads(line) for line in
              (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    logs = [(event["level"], event["message"]) for event in events if event["event"] == "log"]
    for op_id, count in {**expected, "s013": 2}.items():
        assert ("info", f"{op_id}: colors applied {count} of 4") in logs, logs
    unsupported = [message for level, message in logs if "unsupported style key colors" in message]
    assert unsupported == ["s010: unsupported style key colors for this component"], logs


def _logs(tmp_path):
    events = [json.loads(line) for line in
              (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    return [(event["level"], event["message"]) for event in events if event["event"] == "log"]


def test_breakdown_series_take_the_palette_in_select_series_order(tmp_path, capsys, monkeypatch):
    # Release 2.6 b_697880743b4f s011: `set_style colors` on a time series by
    # region waited all 20 s for swatches it never shows, then timed out. Colors
    # apply in order to the breakdown values Select series lists (recipe 1.3).
    palette = ["#0B2559", "#2B6CB0", "#5A8FD4"]
    read = []
    read_colors = style._read_colors

    def recorded(page, ctx, count, series=None):
        # verify's own readback of each series' Line color (Select series).
        read.append(read_colors(page, ctx, count, series))
        return read[-1]

    monkeypatch.setattr(style, "_read_colors", recorded)
    ops, readback = _replay("breakdown_colors.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)
    assert read and read[-1] == [style.rgb(c) for c in palette], read
    logs = _logs(tmp_path)
    assert [message for _, message in logs if "colors applied" in message] == [
        "s003: colors applied 3 of 3"], logs
    assert not [message for level, message in logs if level == "warn"], logs


def test_release_breakdown_colors_end_inside_their_budget(tmp_path, capsys, monkeypatch):
    # Release 2.6 b_697880743b4f on its own view (dss_demo): s011 colors s010, a
    # time series by region (six series), with five colors; it timed out twice.
    _write_png(tmp_path / "background_p1.png", 1200, 892)
    ops, readback = _replay("b_697880743b4f.jsonl", tmp_path, capsys, monkeypatch, own_source=True)
    _assert_readback(ops, readback)
    logs = _logs(tmp_path)
    applied = [int(found[1]) for found in (
        re.fullmatch(r"s011: colors applied (\d) of 5", message) for _, message in logs) if found]
    # One attempt (a retry logs again); colors skipped only for the op's time.
    assert len(applied) == 1 and applied[0] >= 1, logs
    skipped = [message for level, message in logs if level == "warn" and message.startswith("s011")]
    assert all(message.endswith("colors skipped (too little op time left)") for message in skipped), logs


def test_time_series_date_granularity_draws_one_point_per_month(tmp_path, capsys, monkeypatch):
    # Release 2.5 b_36f20b42159c s015 "Revenue by month": the DATE_TRUNC(order_date,
    # MONTH) bucket kept the inferred Date type and drew a daily axis, a spike on
    # each 1st and zeros between. date_granularity month sets Year Month (recipe 1.2).
    ops, readback = _replay("date_granularity.jsonl", tmp_path, capsys, monkeypatch)
    _assert_readback(ops, readback)
    found = readback["s002"]
    assert found["date_type"] == "Year Month", found
    assert found["dimensions"] == ["created_at (Year Month)"], found
    assert found["x_axis"] and all(_MONTH.fullmatch(label) for label in found["x_axis"]), found


def test_page_one_is_renamed_and_saved_beside_an_added_page(tmp_path, capsys, monkeypatch):
    # Release 2.4: every report's page 1 stayed "Untitled Page"; the backend
    # names it with rename_page right after open_report (recipe 1.1).
    _replay("rename_page.jsonl", tmp_path, capsys, monkeypatch)
    events = [json.loads(line) for line in
              (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    selectors = load_selectors()
    with chrome.attached(chrome.ChromeConfig.from_env()) as browser:
        page = browser.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(events[-1]["report_url"] + "/edit", wait_until="domcontentloaded")
            expect(page.locator(selectors["manage_pages"])).to_contain_text("of 2", timeout=20000)
            page.locator(selectors["manage_pages"]).click()
            rows = page.locator(selectors["pages_panel"]).locator(selectors["page_rows"])
            expect(rows).to_have_text(["Overview", "Detail"], timeout=20000)
            page.screenshot(path=str(tmp_path / "pages.png"))
        finally:
            page.close()
