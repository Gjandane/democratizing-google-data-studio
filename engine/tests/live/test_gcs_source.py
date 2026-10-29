"""Live recipe 1.4 GCS CSV header: a FILE source with no billing project.

DSS_TEST_GCS_PATH must name a CSV with the sample's columns: order_date
(YYYY-MM-DD), region, category, quantity and revenue.
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

from dsengine.cli import main
from dsengine.ops import charts
from dsengine.recipe import ENGINE_ROOT, load_recipe

pytestmark = pytest.mark.live
FIXTURE = Path(__file__).parent / "recipes" / "gcs_basic.jsonl"


def test_gcs_csv_recipe(tmp_path, capsys, monkeypatch):
    load_dotenv(ENGINE_ROOT.parent / ".env")
    path = os.environ.get("DSS_TEST_GCS_PATH", "").strip()
    if not path:
        pytest.skip("set DSS_TEST_GCS_PATH to a CSV the signed-in account can read")
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
    # Spike result (2026-10-29): YYYY-MM-DD types as Date, so no contract change.
    assert types["order_date"] == "type_datetime", types
    assert types["revenue"] == types["quantity"] == "type_numeric", types
