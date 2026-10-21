"""Live replay of the op sequence that failed in release build b_31ee6bedd325."""

import json
import os
import shutil
import traceback
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

from dsengine.cli import main
from dsengine.ops import charts, controls
from dsengine.recipe import ENGINE_ROOT

pytestmark = pytest.mark.live

RECIPES = Path(__file__).parent / "recipes"


def _labels(page, ctx, key):
    return charts._field_names(ctx.locator(page, key), ctx)


def _matches(actual, expected):
    return len(actual) == len(expected) and all(
        charts._matches_field(label, field) for label, field in zip(actual, expected)
    )


def test_compiled_recipe_sequence_sets_every_field(tmp_path, capsys, monkeypatch):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    project, dataset, table = os.environ.get(
        "DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items"
    ).split(".")
    records = [json.loads(line) for line in
               (RECIPES / "recipe_replay.jsonl").read_text(encoding="utf-8").splitlines()]
    header = records[0]
    header["build_id"] = f"b_{uuid.uuid4().hex[:12]}"
    header["report_name"] = f"Engine recipe replay {header['build_id']}"
    header["datasource"].update(project_id=project, dataset_id=dataset, table_id=table)
    recipe_path = tmp_path / "recipe_replay.jsonl"
    recipe_path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    shutil.copy(RECIPES / "background_p1.png", tmp_path / "background_p1.png")

    readback = {}
    diagnostics = []
    chart_verify, control_verify = charts.verify, controls.verify

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
    monkeypatch.setattr(charts, "run", observed(charts.run))
    monkeypatch.setattr(controls, "run", observed(controls.run))

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

    for op in records[1:]:
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
        else:
            continue
        expected = (op["x"], op["y"], op["w"], op["h"])
        assert all(abs(a - e) <= 4 for a, e in zip(found["box"], expected)), (op["id"], found)
    assert len(readback) == sum(op["op"] in {"add_chart", "add_control"} for op in records[1:])
