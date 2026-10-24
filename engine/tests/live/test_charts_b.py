"""Live acceptance for remaining charts and page-wide controls."""

import json
import os
import re
import time
import traceback
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from playwright.sync_api import expect

from dsengine import chrome
from dsengine.cli import main
from dsengine.ops import charts, controls, OperationError
from dsengine.recipe import ENGINE_ROOT
from dsengine.selectors import load_selectors

pytestmark = pytest.mark.live


def _records(name="charts_b.jsonl"):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    records = [json.loads(line) for line in (
        Path(__file__).parent / "recipes" / name
    ).read_text().splitlines()]
    project, dataset, table = os.getenv(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    records[0]["datasource"].update(project_id=project, dataset_id=dataset, table_id=table)
    records[0]["build_id"] = "b_" + uuid.uuid4().hex[:12]
    records[0]["report_name"] += " " + records[0]["build_id"]
    return records


def _run(records, tmp_path, capsys):
    recipe = tmp_path / "charts_b.jsonl"
    recipe.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    code = main(["run", str(recipe), "--screens", str(tmp_path / "screens")])
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out)
    assert code == 0, output.out + output.err
    return [json.loads(line) for line in output.out.splitlines()]


def test_remaining_chart_types_and_controls(tmp_path, capsys, monkeypatch):
    records = _records()
    diagnostics = []
    evidence = []
    for module in (charts, controls):
        run = module.run
        verify = module.verify

        def observed(page, op, ctx, run=run):
            try:
                return run(page, op, ctx)
            except Exception:
                diagnostics.append(traceback.format_exc())
                raise

        def checked(page, op, ctx, verify=verify):
            verify(page, op, ctx)
            evidence.append({"op_id": op.id, "setup": ctx.state[op.id]})

        monkeypatch.setattr(module, "run", observed)
        monkeypatch.setattr(module, "verify", checked)
    try:
        events = _run(records, tmp_path, capsys)
    finally:
        (tmp_path / "diagnostics.txt").write_text("\n".join(diagnostics))
    finished = [e for e in events if e["event"] == "op_finished"]
    assert len(finished) == len(records) - 1
    geo = next(e for e in finished if e["op_id"] == "s004")
    # The task explicitly permits only this failure when the test source has
    # no compatible geo field. All other operations must succeed.
    assert geo["status"] == "ok" or (
        geo["status"] == "failed" and "cannot map to a geo type" in geo["message"]
    ), (finished, diagnostics)
    assert all(e["status"] == "ok" for e in finished if e is not geo), (finished, diagnostics)
    assert events[-1]["status"] == ("partial" if geo["status"] == "failed" else "ok")
    assert events[-1]["report_url"] and not events[-1]["report_url"].endswith("/edit")
    selectors = load_selectors()
    with chrome.attached(chrome.ChromeConfig.from_env()) as browser:
        page = browser.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(events[-1]["report_url"], wait_until="domcontentloaded")
            components = page.locator(selectors["components"])
            expect(components).to_have_count(6, timeout=20000)
            for component, op in zip(components.all(), records[2:8]):
                assert all(abs(a - op[k]) <= 4 for a, k in zip(
                    charts._geometry(component), ("x", "y", "w", "h")
                ))
            pivot = components.nth(0)
            expect(pivot).to_contain_text("sale_price", timeout=20000)
            scatter = components.nth(1).locator(selectors["chart_iframe"])
            expect(scatter).to_have_count(1, timeout=20000)
            expect(scatter.content_frame.locator(selectors["chart_frame_body"])).to_contain_text(
                re.compile(r"\d"), timeout=20000
            )
            time_series = components.nth(3).locator(selectors["chart_iframe"])
            expect(time_series).to_have_count(1, timeout=20000)
            rendered = time_series.content_frame.locator(selectors["chart_frame_body"])
            expect(rendered).to_contain_text(re.compile(r"\d"), timeout=20000)
            before = rendered.inner_text()
            expect(page.locator(selectors["loading"])).to_have_count(0, timeout=20000)
            page.screenshot(path=str(tmp_path / "saved_report.png"), full_page=True)
            components.nth(4).click()
            page.locator(selectors["date_range_options"]).click()
            page.locator(selectors["last_7_days"]).click()
            # This is a preset family; choose the exact range in its submenu.
            page.locator(selectors["last_overlay"]).locator(selectors["last_7_days"]).click()
            page.locator(selectors["date_apply"]).click()
            expect(components.nth(4)).not_to_contain_text("Select date range")
            # Rendering can briefly clear and restore the old chart before the
            # filtered query finishes. Require changed numeric content together.
            deadline = time.monotonic() + 20
            while True:
                after = rendered.inner_text()
                if after != before and re.search(r"\d", after):
                    break
                assert time.monotonic() < deadline, "date control did not filter the time series"
                page.wait_for_timeout(250)
            expect(page.locator(selectors["loading"])).to_have_count(0, timeout=20000)
            page.screenshot(path=str(tmp_path / "date_filtered.png"), full_page=True)
            # Independently inspect persisted Setup fields and both scatter axes.
            page.goto(events[-1]["report_url"] + "/edit", wait_until="domcontentloaded")
            expect(components).to_have_count(6, timeout=20000)
            checks = [(0, "pivot_rows_group", ["status"]),
                      (0, "pivot_columns_group", []),
                      (1, "scatter_x_group", ["sale_price"]),
                      (1, "scatter_y_group", ["order_id"]),
                      (5, "control_field_group", ["status"])]
            for index, key, fields in checks:
                components.nth(index).click(position={"x": 10, "y": 10})
                page.keyboard.press("Escape")
                page.locator(selectors["setup_tab"]).click()
                group = page.locator(selectors[key])
                expect(group).to_be_visible()
                chips = group.locator(selectors["field_chips"])
                expect(chips).to_have_count(len(fields))
                actual = chips.evaluate_all("es=>es.map(e=>e.getAttribute('aria-label'))")
                assert actual == fields
            (tmp_path / "evidence.json").write_text(json.dumps({
                "events": events, "setup": evidence, "date_before": before, "date_after": after,
            }, indent=2))
        except Exception:
            detail = traceback.format_exc()
            (tmp_path / "saved_failure.txt").write_text(detail)
            raise AssertionError(detail) from None
        finally:
            page.close()


def test_controls_retry_and_remaining_chart_variants(tmp_path, capsys, monkeypatch):
    records = _records()
    date = dict(records[6], id="s002")
    scatter = dict(records[3], id="s003", title=None,
                   metrics=records[3]["metrics"] + [{"field": "id", "agg": "count"}])
    pivot = dict(records[2], id="s004", title=None,
                 options={"row_dimensions": ["status"], "column_dimensions": ["product_id"]},
                 sort={"field": "sale_price", "order": "asc"})
    dropdown = dict(records[7], id="s005", w=1400)
    missing = dict(dropdown, id="s006", field="__missing_field__")
    bad_scatter = dict(scatter, id="s007", metrics=scatter["metrics"][:1])
    bad_pivot = dict(pivot, id="s008", options={"row_dimensions": "status"})
    empty_rows = dict(pivot, id="s009", options={"row_dimensions": [], "column_dimensions": ["status"]})
    ops = [records[1], date, scatter, pivot, dropdown, missing,
           bad_scatter, bad_pivot, empty_rows, dict(records[8], id="s010"), dict(records[9], id="s011")]
    original_run = controls.run
    original_verify = controls.verify
    attempts = []
    counts = []

    def retry_once(page, op, ctx):
        result = original_run(page, op, ctx)
        if op.id == "s002":
            attempts.append(op.id)
            if len(attempts) == 1:
                raise OperationError("injected transient control setup failure")
        return result

    def count_components(page, op, ctx):
        original_verify(page, op, ctx)
        counts.append(ctx.locator(page, "components").count())

    monkeypatch.setattr(controls, "run", retry_once)
    monkeypatch.setattr(controls, "verify", count_components)
    events = _run([records[0], *ops], tmp_path, capsys)
    finished = [e for e in events if e["event"] == "op_finished"]
    assert [e["status"] for e in finished] == ["ok"] * 5 + ["failed"] * 4 + ["ok"] * 2, finished
    assert finished[5]["message"] == "field __missing_field__ not in data source"
    assert "scatter requires X and Y metrics" in finished[6]["message"]
    assert "lists of field names" in finished[7]["message"]
    assert "at least one row dimension" in finished[8]["message"]
    assert len(attempts) == 2
    assert counts == [1, 4]
    assert any(e["event"] == "log" and "clamped" in e["message"] for e in events)
    assert events[-1]["status"] == "partial"


REPORT_QUALITY = ENGINE_ROOT.parent / "data" / "report-quality"


def test_area_variants_and_percent_stacked_bars(tmp_path, capsys, monkeypatch):
    # Recipe 1.3 (task 13.2): release 2.6's urban/rural area charts and 100% split bar.
    records = _records("area_charts.jsonl")
    read_back = {}
    verify = charts.verify

    def checked(page, op, ctx):
        verify(page, op, ctx)
        # Independently of the engine's check: verify leaves the Style tab open.
        switch = lambda key: (ctx.locator(page, key).count() > 0
                              and ctx.locator(page, key).first.is_visible()
                              and ctx.locator(page, key).first.get_attribute("aria-checked") == "true")
        stack_key = "stacked_switch" if op.chart_type == "bar" else "area_stack_switch"
        found = {"stacked": switch(stack_key), "percent": switch("percent_stack_switch")}
        if op.chart_type == "area":
            ctx.locator(page, "setup_tab").click()
            ctx.locator(page, "dimension_group_any").locator(
                ctx.selectors["dimension_type_button"]).first.click()
            control = ctx.locator(page, "data_type_control")
            control.wait_for(state="visible")
            found["date_type"] = control.inner_text().splitlines()[0].strip()
            page.keyboard.press("Escape")
        read_back[op.id] = found

    monkeypatch.setattr(charts, "verify", checked)
    events = _run(records, tmp_path, capsys)
    finished = [e for e in events if e["event"] == "op_finished"]
    assert [e["status"] for e in finished] == ["ok"] * (len(records) - 1), finished
    assert events[-1]["status"] == "ok" and events[-1]["report_url"]
    variants = {e["message"].split(": ", 1)[0]: e["message"].split(": ", 1)[1] for e in events
                if e["event"] == "log" and e.get("level") == "info"
                and e["message"].split(": ", 1)[0] in {"s002", "s003", "s004", "s005"}}
    assert variants == {"s002": "Area", "s003": "Stacked area", "s004": "100% stacked area",
                        "s005": "100% stacked bar"}, events
    assert read_back == {
        "s002": {"stacked": False, "percent": False, "date_type": "Year Month"},
        "s003": {"stacked": True, "percent": False, "date_type": "Year Month"},
        "s004": {"stacked": True, "percent": True, "date_type": "Year Month"},
        "s005": {"stacked": True, "percent": True},
    }, read_back

    selectors = load_selectors()
    with chrome.attached(chrome.ChromeConfig.from_env()) as browser:
        page = browser.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(events[-1]["report_url"], wait_until="domcontentloaded")
            page.bring_to_front()
            components = page.locator(selectors["components"])
            expect(components).to_have_count(4, timeout=30000)
            for component, op in zip(components.all(), records[2:6]):
                assert all(abs(a - op[k]) <= 4 for a, k in zip(
                    charts._geometry(component), ("x", "y", "w", "h")))
                frame = component.locator(selectors["chart_iframe"])
                expect(frame).to_have_count(1, timeout=30000)
                expect(frame.content_frame.locator(selectors["chart_frame_body"])).to_contain_text(
                    re.compile(r"\d"), timeout=45000)
            for index in (0, 1, 2):
                expect(components.nth(index).locator(selectors["component_area"])).to_have_count(1)
            expect(page.locator(selectors["loading"])).to_have_count(0, timeout=30000)
            REPORT_QUALITY.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(REPORT_QUALITY / "engine-13.2-area.png"), timeout=120000)
            (tmp_path / "evidence.json").write_text(json.dumps(
                {"events": events, "read_back": read_back}, indent=2))
        finally:
            page.close()
