"""Live recipe 1.4 GCS CSV header: a FILE source with no billing project.

Recipe 1.5: runs once with no template (a visitor's agent: un-aliased ds.* params on
Data Studio's default report) and once with DSS_TEMPLATE_REPORT_ID if it is set.

DSS_TEST_GCS_PATH must name a CSV with the sample's columns: order_date
(YYYY-MM-DD), region, category, quantity and revenue.
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

from dsengine import executor
from dsengine.cli import main
from dsengine.ops import charts, pages, report
from dsengine.recipe import ENGINE_ROOT, load_recipe

pytestmark = pytest.mark.live
FIXTURE = Path(__file__).parent / "recipes" / "gcs_basic.jsonl"


@pytest.mark.parametrize("template", ["none", "configured"])
def test_gcs_csv_recipe(tmp_path, capsys, monkeypatch, template):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    path = os.environ.get("DSS_TEST_GCS_PATH", "").strip()
    if not path:
        pytest.skip("set DSS_TEST_GCS_PATH to a CSV the signed-in account can read")
    if template == "none":
        # Empty, not unset, so the CLI's dotenv can't restore the root .env's template.
        monkeypatch.setenv("DSS_TEMPLATE_REPORT_ID", "")
    elif not os.environ.get("DSS_TEMPLATE_REPORT_ID", "").strip():
        pytest.skip("DSS_TEMPLATE_REPORT_ID is not set")
    # A visitor's machine has no billing project; an empty value keeps dotenv from
    # restoring the root .env's GCP_PROJECT_ID inside the CLI.
    monkeypatch.setenv("GCP_PROJECT_ID", "")
    records = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    records[0]["datasource"]["path"] = path
    records[0]["build_id"] = "b_" + uuid.uuid4().hex[:12]
    records[0]["report_name"] += " " + records[0]["build_id"]
    recipe = tmp_path / "gcs_basic.jsonl"
    recipe.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    load_recipe(recipe)

    # Record Data Studio's CSV type inference (the field's type icon) at readiness.
    types = {}
    source_fields = charts._source_fields

    def observed(page, ctx):
        names = source_fields(page, ctx)
        if not types:
            types.update(ctx.locator(page, "field_buttons").evaluate_all(
                "(es, icon) => Object.fromEntries(es.map(e => [e.getAttribute('aria-label'), "
                "e.querySelector(icon)?.getAttribute('data-mat-icon-name')]))",
                ctx.selectors["field_type_icon"]))
        return names

    monkeypatch.setattr(charts, "_source_fields", observed)
    # Before saving, page 1 must hold only the recipe's charts (the default report's
    # starter components are deleted by open_report).
    placed = []
    save = report._RUNNERS["save_report"]

    def counted(page, op, ctx):
        placed.append((pages.current(page, ctx), ctx.locator(page, "components").count()))
        return save(page, op, ctx)

    monkeypatch.setitem(report._RUNNERS, "save_report", counted)
    opened = []
    build_url = executor.build_url
    monkeypatch.setattr(executor, "build_url", lambda header: opened.append(build_url(header)) or opened[-1])
    code = main(["run", str(recipe), "--screens", str(tmp_path / "screens")])
    output = capsys.readouterr()
    (tmp_path / "events.jsonl").write_text(output.out)
    with capsys.disabled():
        print("\nGCS field types:", json.dumps(types, ensure_ascii=False))
    events = [json.loads(line) for line in output.out.splitlines()]
    assert code == 0, output.out + output.err
    final = events[-1]
    assert (final["event"], final["status"], final["failed"]) == ("run_finished", "ok", 0), final
    assert final["report_url"].startswith("https://datastudio.google.com/"), final
    charts_placed = sum(row.get("op") == "add_chart" for row in records[1:])
    assert placed == [((1, 1), charts_placed)], placed
    assert len(opened) == 1 and ("ds.ds0" in opened[0]) == (template == "configured"), opened
    # Spike result (2026-10-29): YYYY-MM-DD types as Date, so no contract change.
    assert types["order_date"] == "type_datetime", types
    assert types["revenue"] == types["quantity"] == "type_numeric", types
