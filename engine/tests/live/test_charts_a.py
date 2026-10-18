"""Live acceptance test for the first five Data Studio chart types."""

import json
import os
import re
import uuid
import traceback
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import load_dotenv
from playwright.sync_api import expect

from dsengine import chrome
from dsengine.cli import main
from dsengine.recipe import ENGINE_ROOT
from dsengine.ops import charts, OperationError
from dsengine.selectors import load_selectors

pytestmark = pytest.mark.live


def _wait_rendered(component, op, selectors):
    if op["chart_type"] in {"time_series", "bar", "pie"}:
        iframe = component.locator(selectors["chart_iframe"])
        expect(iframe).to_have_count(1, timeout=20000)
        expect(iframe.content_frame.locator(selectors["chart_frame_body"])).to_contain_text(
            re.compile(r"\d"), timeout=20000
        )
    else:
        expect(component).to_contain_text(op["metrics"][0]["field"], timeout=20000)


def test_five_chart_types_save_a_view_link(tmp_path, capsys, monkeypatch):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    table = os.environ.get("DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items")
    project, dataset, table_name = table.split(".")
    build_id = f"b_{uuid.uuid4().hex[:12]}"
    fixture = Path(__file__).parent / "recipes" / "charts_a.jsonl"
    records = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    records[0]["build_id"] = build_id
    records[0]["report_name"] = f"Engine charts A {build_id}"
    records[0]["datasource"] = {
        "connector": "bigQuery",
        "project_id": project,
        "dataset_id": dataset,
        "table_id": table_name,
    }
    recipe_path = tmp_path / "charts_a.jsonl"
    recipe_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    diagnostics = []
    chart_evidence = []
    original_run = charts.run
    original_verify = charts.verify

    def observed_run(page, op, ctx):
        try:
            return original_run(page, op, ctx)
        except Exception:
            diagnostics.append(traceback.format_exc())
            raise

    monkeypatch.setattr(charts, "run", observed_run)

    def observed_verify(page, op, ctx):
        original_verify(page, op, ctx)
        chart_evidence.append({
            "op_id": op.id,
            "type": op.chart_type,
            "setup": ctx.state[op.id],
            "box": charts._geometry(ctx.locator(page, "chart_components").last),
        })

    monkeypatch.setattr(charts, "verify", observed_verify)
    exit_code = main(["run", str(recipe_path), "--screens", str(tmp_path / "screens")])
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out, encoding="utf-8")
    (tmp_path / "diagnostics.txt").write_text("\n".join(diagnostics), encoding="utf-8")
    assert exit_code == 0, f"{output.err}\n{output.out}\n{diagnostics}"
    assert output.err == ""
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [event for event in events if event["event"] == "op_finished"]
    assert len(finished) == 8
    assert [event["status"] for event in finished] == ["ok"] * 8, ([
        (event["op_id"], event["status"], event["message"]) for event in finished
    ], diagnostics)
    run_finished = events[-1]
    assert run_finished["event"] == "run_finished"
    assert run_finished["status"] == "ok"
    assert (run_finished["ok"], run_finished["failed"], run_finished["skipped"]) == (8, 0, 0)
    parsed = urlsplit(run_finished["report_url"])
    assert parsed.hostname in {"datastudio.google.com", "lookerstudio.google.com"}
    assert "/reporting/" in parsed.path
    assert "/create" not in parsed.path
    assert not parsed.path.endswith("/edit")

    # Read the report this test just created in a fresh owned tab. A saved URL
    # alone does not establish that the components and rendering persisted.
    selectors = load_selectors()
    chart_ops = [record for record in records if record.get("op") == "add_chart"]
    with chrome.attached(chrome.ChromeConfig.from_env()) as browser_context:
        page = browser_context.new_page()
        try:
            page.set_viewport_size({"width": 1920, "height": 1200})
            page.goto(run_finished["report_url"], wait_until="domcontentloaded")
            components = page.locator(selectors["chart_components"])
            expect(components).to_have_count(5, timeout=20000)
            for index, op in enumerate(chart_ops):
                component = components.nth(index)
                assert all(abs(actual - op[key]) <= 4 for actual, key in zip(
                    charts._geometry(component), ("x", "y", "w", "h")
                ))
                expect(component).to_contain_text(op["title"], timeout=20000)
                _wait_rendered(component, op, selectors)
            page.screenshot(path=str(tmp_path / "saved_report.png"), full_page=True)
            # Read saved Setup panels independently of the production verifier.
            page.goto(run_finished["report_url"] + "/edit", wait_until="domcontentloaded")
            components = page.locator(selectors["chart_components"])
            expect(components).to_have_count(5, timeout=20000)
            for index, op in enumerate(chart_ops):
                _wait_rendered(components.nth(index), op, selectors)
            aggregation_labels = {"sum": "Sum", "avg": "Average", "count_distinct": "Count Distinct"}
            for index, op in enumerate(chart_ops):
                components.nth(index).click(position={"x": 10, "y": 10})
                page.locator(selectors["setup_tab"]).click()
                metrics = page.locator(selectors["metric_group_any"])
                labels = metrics.locator(selectors["field_chips"]).evaluate_all(
                    "es => es.map(e => e.getAttribute('aria-label'))"
                )
                assert labels == [metric["field"] for metric in op["metrics"]]
                dimensions = list(op["dimensions"])
                if op.get("date_dimension"):
                    dimensions.insert(0, op["date_dimension"])
                if dimensions:
                    actual = page.locator(selectors["dimension_group_any"]).locator(
                        selectors["field_chips"]
                    ).evaluate_all("es => es.map(e => e.getAttribute('aria-label'))")
                    assert len(actual) == len(dimensions)
                    assert all(label == field or label.startswith(field + " (")
                               for label, field in zip(actual, dimensions))
                page.screenshot(path=str(tmp_path / f"{op['id']}_saved_setup.png"), full_page=True)
                for metric_index, metric in enumerate(op["metrics"]):
                    metrics.locator(selectors["metric_chips"]).nth(metric_index).locator(
                        selectors["metric_aggregation_button"]
                    ).click()
                    control = page.locator(selectors["metric_editor"]).locator(
                        selectors["aggregation_control"]
                    )
                    expect(control).to_have_accessible_name("Aggregation " + aggregation_labels[metric["agg"]])
                    page.keyboard.press("Escape")
        except Exception:
            detail = traceback.format_exc()
            (tmp_path / "saved_report_failure.txt").write_text(detail, encoding="utf-8")
            # Preserve the failing saved-report action: attached() deliberately
            # sanitizes Playwright errors for the public CLI.
            raise AssertionError(detail) from None
        finally:
            page.close()
    (tmp_path / "evidence.json").write_text(json.dumps({
        "report_url": run_finished["report_url"],
        "events": events,
        "charts": chart_evidence,
    }, indent=2), encoding="utf-8")


@pytest.mark.parametrize("bar_metrics", [
    [{"field": "sale_price", "agg": "sum"}],
    [{"field": "sale_price", "agg": "sum"}, {"field": "order_id", "agg": "count_distinct"}],
], ids=["single-series", "multiple-series"])
def test_chart_variants_retry_clamp_and_rejected_fields(tmp_path, capsys, monkeypatch, bar_metrics):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    fixture = Path(__file__).parent / "recipes" / "charts_a.jsonl"
    records = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    header = records[0]
    project, dataset, table = os.environ.get(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    header["datasource"].update(project_id=project, dataset_id=dataset, table_id=table)
    header["build_id"] = f"b_{uuid.uuid4().hex[:12]}"
    header["report_name"] = f"Engine chart variants {header['build_id']}"
    bar = dict(records[4], id="s002", title=None, x=24, y=24, w=560, h=300,
               dimensions=["status", "created_at"], date_dimension="returned_at",
               metrics=bar_metrics,
               sort={"field": "status", "order": "asc"},
               options={"orientation": "vertical", "stacked": True})
    time_series = dict(records[3], id="s003", title=None, x=620, y=24, w=556, h=300,
                       breakdown="status")
    table_op = dict(records[6], id="s004", title=None, x=24, y=400, w=1300, h=400,
                    dimensions=["status", "created_at"],
                    metrics=[{"field": "sale_price", "agg": "max"}], options={})
    unknown = dict(records[2], id="s005", component_id="p1_unknown",
                   metrics=[{"field": "__missing_field__", "agg": "sum"}])
    empty = dict(records[2], id="s006", component_id="p1_empty", metrics=[])
    ops = [records[1], bar, time_series, table_op, unknown, empty, records[7], records[8]]
    recipe_path = tmp_path / "variants.jsonl"
    recipe_path.write_text("\n".join(json.dumps(row) for row in [header, *ops]) + "\n", encoding="utf-8")
    configure = charts._set_title_and_options
    run = charts.run
    diagnostics = []
    attempts = []
    counts = []
    verify = charts.verify

    def transient_setup_failure(page, ctx, op):
        configure(page, ctx, op)
        if op.id == "s002":
            attempts.append(op.id)
            if len(attempts) == 1:
                raise OperationError("injected transient chart setup failure")

    def observe_count(page, op, ctx):
        verify(page, op, ctx)
        counts.append(ctx.locator(page, "chart_components").count())

    def observed_run(page, op, ctx):
        try:
            return run(page, op, ctx)
        except Exception:
            diagnostics.append(traceback.format_exc())
            raise

    monkeypatch.setattr(charts, "_set_title_and_options", transient_setup_failure)
    monkeypatch.setattr(charts, "verify", observe_count)
    monkeypatch.setattr(charts, "run", observed_run)
    code = main(["run", str(recipe_path), "--screens", str(tmp_path / "screens")])
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out, encoding="utf-8")
    (tmp_path / "diagnostics.txt").write_text("\n".join(diagnostics), encoding="utf-8")
    assert code == 0, output.out
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [event for event in events if event["event"] == "op_finished"]
    assert [event["status"] for event in finished] == ["ok"] * 4 + ["failed"] * 2 + ["ok"] * 2, output.out
    assert finished[4]["message"] == "field __missing_field__ not in data source"
    assert "requires at least one metric" in finished[5]["message"]
    assert counts == [1, 2, 3]  # Retry and rejected fields must not duplicate charts.
    assert len(attempts) == 2
    assert any(event["event"] == "log" and "clamped" in event["message"] for event in events)
    assert events[-1]["status"] == "partial"
    assert events[-1]["report_url"]
