"""Task 11.3: bounded extraction, code-owned classification, persistence and invalidation."""
import copy
import json
import time
from pathlib import Path

import pytest

from dss.harness.context import BUDGETS, requirement_sections
from dss.memory import episodic
from dss.spec import capabilities, requirements as req
from fakes import FakeLLM
from test_audit_style import drain
from test_references import Capture, output, png
from test_thin_slice import thin, load


def check(client, app, bid):
    result = client.post(f"/api/builds/{bid}/feasibility/check")
    assert result.status_code == 202, result.text
    client.portal.call(drain, app)
    return result.json()["run_id"], client.get(f"/api/builds/{bid}/feasibility").json()


def extracted(source_id, capability="chart.bar", text="Show a bar chart", **kwargs):
    return {"source_id": source_id, "text": text, "needs": [{"capability": capability}], **kwargs}


def user(app, bid, text):
    return episodic.save(app.state.db, bid, "user", text)["id"]


def use_model(monkeypatch, app, *items):
    model = Capture(response=json.dumps({"requirements": list(items)}), requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    return model


def source(app, bid, **fields):
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", ("s_test", bid, "bigquery", "sales", "p.d.t", 10,
            json.dumps([{"name": name, "type": kind} for name, kind in fields.items()])))


def test_legacy_check_one_trace_no_side_effects(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    assets = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    model = use_model(monkeypatch, app)
    assert client.get(f"/api/builds/{bid}/feasibility").json() == req.Assessment().model_dump()
    run, result = check(client, app, bid)
    assert result["state"] == "ready" and result["id"] and result["input_digest"]
    assert model.calls == 0  # Deterministic legacy spec check needs no extraction.
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM traces WHERE run_id=?", (run,)).fetchone()[0] == 1
        events = [r[0] for r in conn.execute("SELECT kind FROM events WHERE run_id=? ORDER BY rowid", (run,))]
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE run_id=?", (run,)).fetchone()[0])
    assert events[0] == "run.started" and events[-1] == "run.finished" and "docs.updated" in events
    assert "capability_check" in [s["node"] for s in spans]
    assert all((folder / name).read_bytes() == value for name, value in assets.items())
    assert not (folder / "recipe.jsonl").exists()
    assert "Feasibility" in client.get(f"/api/builds/{bid}/docs/feasibility.md").text
    ledger_bytes = (folder / "requirements.json").read_bytes()
    for _ in range(3):
        assert client.get(f"/api/builds/{bid}/feasibility").json() == result
    assert model.calls == 0 and (folder / "requirements.json").read_bytes() == ledger_bytes


def test_extraction_keeps_provenance_and_mapping(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Bar chart: revenue by region, sum, USD, month")
    source(app, bid, revenue="FLOAT", region="STRING")
    model = use_model(monkeypatch, app, extracted(sid, mappings=[{"label": "Revenue", "field": "revenue",
        "aggregation": "sum", "unit": "USD", "date_grain": "month"}]))
    run, result = check(client, app, bid)
    assert result["state"] == "ready", result
    assert model.calls == 1
    ledger = req.load(folder)
    r = ledger.requirements[0]
    assert r.source.id == sid and r.source.kind == "message"
    assert r.mappings[0].model_dump() == {"label": "Revenue", "field": "revenue", "aggregation": "sum", "unit": "USD", "date_grain": "month"}
    evidence = ledger.verification[r.id]
    assert evidence[0]["status"] == "supported" and evidence[0]["evidence"]
    assert evidence[1]["schema_type"] == "FLOAT" and evidence[1]["source_id"] == sid
    first_id = r.id
    check(client, app, bid)
    assert model.calls == 1 and req.load(folder).requirements[0].id == first_id
    request = model.requests[0]
    assert request.config.max_output_tokens == 4000
    assert BUDGETS["capability_check"] == 12000 and not request.config.tools
    assert "source_id" in json.dumps(request.config.response_json_schema)


@pytest.mark.parametrize("capability,status", [
    ("feature.telepathy", "unknown"), ("animation.temporal_playback", "unsupported_app"),
    ("extension.community_visualization", "unsupported_app"), ("control.fixed_size_list", "unsupported_app"),
    ("geo.lat_long_points", "unsupported_app"), ("chart.time_series", "needs_data")])
def test_code_classifies_support_scopes(thin, monkeypatch, capability, status):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show the requested behavior")
    use_model(monkeypatch, app, extracted(sid, capability))
    _, result = check(client, app, bid)
    assert result["state"] == "blocked" and result["issues"][0]["status"] == status
    assert result["issues"][0]["resolution"] == "unresolved"
    if status == "unknown":
        assert "clarify" in result["issues"][0]["reason"]


def test_gross_net_model_suggestion_requires_definition(thin, monkeypatch):
    client, app, bid, folder = thin
    source(app, bid, gross_sales="FLOAT", net_sales="FLOAT")
    sid = user(app, bid, "Show Revenue")
    use_model(monkeypatch, app, extracted(sid, "chart.scorecard", mappings=[{"label": "Revenue", "field": "gross_sales",
        "unit": "USD", "aggregation": "sum", "date_grain": "month"}]))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "needs_clarification"
    assert "gross_sales" in a["issues"][0]["reason"]


def test_native_product_exclusion_is_distinct(thin, monkeypatch):
    """The seed has no proven product exclusions; exercise the registry's supported state shape."""
    client, app, bid, folder = thin
    raw = capabilities.load_registry().model_dump(mode="json")
    cap = next(c for c in raw["capabilities"] if c["id"] == "control.fixed_size_list")
    cap["native_product"]["status"] = "unsupported"
    registry = capabilities.Registry.model_validate(raw)
    monkeypatch.setattr("dss.harness.nodes.capability_check.load_registry", lambda: registry)
    monkeypatch.setattr("dss.api.feasibility.load_registry", lambda: registry)
    sid = user(app, bid, "A product-excluded feature")
    use_model(monkeypatch, app, extracted(sid, "control.fixed_size_list"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unsupported_product"


@pytest.mark.parametrize("count,finish,raw", [(4001, "STOP", None), (4000, "MAX_TOKENS", '{"requirements":[')])
def test_output_token_limit_blocks_without_repair(thin, monkeypatch, count, finish, raw):
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    client, app, bid, folder = thin
    sid = user(app, bid, "Show a bar")
    class OverOutput(FakeLLM):
        async def generate_content_async(self, request, stream=False):
            self.calls += 1
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=self.response)]),
                finish_reason=types.FinishReason(finish),
                usage_metadata=types.GenerateContentResponseUsageMetadata(candidates_token_count=count))
    model = OverOutput(response=raw or json.dumps({"requirements": [extracted(sid)]}))
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and "4k output" in a["issues"][0]["reason"] and model.calls == 1


@pytest.mark.parametrize("text,field,agg,state", [
    ("Show Revenue; I have gross_sales and net_sales", "gross_sales", "sum", "blocked"),
    ("Revenue is gross_sales or net_sales; sum in USD by month", "gross_sales", "sum", "blocked"),
    ("Do not use gross_sales for Revenue", "gross_sales", None, "blocked"),
    ("Use net_sales for Revenue; sum in USD by month", "net_sales", "sum", "ready"),
    ("Revenue means net_sales; average in USD by month", "net_sales", "sum", "blocked"),
    ("Revenue means net_sales; average in USD by month", "net_sales", "avg", "ready")])
def test_mapping_definition_and_aggregation_are_not_inferred(thin, monkeypatch, text, field, agg, state):
    client, app, bid, folder = thin
    source(app, bid, gross_sales="FLOAT", net_sales="FLOAT")
    sid = user(app, bid, text)
    use_model(monkeypatch, app, extracted(sid, mappings=[{"label": "Revenue", "field": field,
        "aggregation": agg, "unit": "USD", "date_grain": "month"}]))
    _, a = check(client, app, bid)
    assert a["state"] == state
    if state == "blocked":
        assert all(i["status"] == "needs_clarification" for i in a["issues"])


def test_removed_source_field_not_resurrected_by_old_spec(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    source(app, bid, revenue="FLOAT", region="STRING")
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "ready"
    with app.state.db.connect() as conn:
        conn.execute("UPDATE sources SET columns_json=? WHERE build_id=?", (json.dumps([{"name": "region", "type": "STRING"}]), bid))
    assert client.get(f"/api/builds/{bid}/feasibility").json()["state"] == "stale"
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any(i["status"] == "needs_data" and "revenue" in i["reason"] for i in a["issues"])


def test_view_pipeline_derived_fields_remain_available():
    snapshot = {"sources": [{"columns": [{"name": "sales", "type": "FLOAT"}]}], "definitions": {"derived-fields.md":
        '---\nview: p.d.view\nfields:\n- name: doubled\n  sql: sales * 2\n  type: FLOAT\n---\n'},
        "spec": {"datasource": {"table": "p.d.view", "fields": [{"name": "sales", "type": "FLOAT"}, {"name": "doubled", "type": "FLOAT"}]}}}
    assert req.schema(snapshot) == {"sales": "FLOAT", "doubled": "FLOAT"}
    snapshot["sources"][0]["columns"] = []
    assert req.schema(snapshot) == {}


def test_schema_uses_code_owned_normalization_and_physical_types(thin):
    client, app, bid, folder = thin
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", ("s_test", bid, "bigquery", "sales", "p.d.t", 10,
            json.dumps([{"name": "Order Total", "type": "number", "bq_type": "FLOAT"},
                        {"name": "OrderDate", "type": "string", "bq_type": "STRING", "date_like": True}])))
    assert req.schema(req.inputs(app.state.db, bid, folder)) == {"order_total": "FLOAT", "orderdate": "DATE"}


def test_missing_mapping_is_data_not_product_failure(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show latitude")
    use_model(monkeypatch, app, extracted(sid, mappings=[{"label": "Latitude", "field": "latitude"}]))
    _, a = check(client, app, bid)
    assert a["issues"][0]["status"] == "needs_data"


def test_unsupported_ledger_survives_supported_spec(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, "A bar chart and animate GPS points along a route")
    model = use_model(monkeypatch, app, extracted(sid), extracted(sid, "animation.temporal_playback", "Animate GPS points along a route"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any(i["status"] == "unsupported_app" for i in a["issues"])
    # Rechecking cannot strip the original unsupported requirement or call the model again.
    _, b = check(client, app, bid)
    assert b["state"] == "blocked" and len(req.load(folder).requirements) == 2 and model.calls == 1


def test_duplicate_descriptions_cannot_hide_an_unsupported_need(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "A bar chart and animated points")
    use_model(monkeypatch, app, extracted(sid), extracted(sid, "animation.temporal_playback"))
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unsupported_app"
    assert len(req.load(folder).requirements[0].needs) == 2


def test_omitted_source_fails_closed(thin, monkeypatch):
    client, app, bid, folder = thin
    user(app, bid, "A requirement the model forgot")
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and a["issues"][0]["status"] == "unknown"


@pytest.mark.parametrize("spoof", ["status", "resolution", "source_id"])
def test_model_cannot_grant_support_or_spoof_provenance(thin, monkeypatch, spoof):
    client, app, bid, folder = thin
    sid = user(app, bid, "Animate GPS points")
    item = extracted(sid, "animation.temporal_playback")
    item[spoof] = {"status": "supported", "resolution": "dropped", "source_id": "fake"}[spoof]
    model = use_model(monkeypatch, app, item)
    _, a = check(client, app, bid)
    assert a["state"] != "ready" and model.calls == 1 and not (folder / "requirements.json").exists()


def test_undeclared_animation_on_map_rejected(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    spec = json.loads((folder / "spec.json").read_text())
    spec["pages"][0]["components"][0].update(type="geo_map", options={"animate": True})
    (folder / "spec.json").write_text(json.dumps(spec))
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any("animate" in i["reason"] for i in a["issues"])


def test_reference_replacement_deletion_sticky_prototype_staleness(thin, monkeypatch):
    from dss.spec import references
    client, app, bid, folder = thin
    load(client, bid)
    use_model(monkeypatch, app)
    check(client, app, bid)
    monkeypatch.setattr(references, "decode", lambda _: None)
    vision = Capture(response=output(items=[]), requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: vision)
    def upload():
        response = client.post(f"/api/builds/{bid}/reference-images", data={"mode": "recreate"},
            files=[("files", ("a.png", png(), "image/png"))])
        assert response.status_code == 202
        client.portal.call(drain, app)
    upload()
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["id"] is None and a["prototype_stale"]
    use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "ready" and a["prototype_stale"]
    assert client.delete(f"/api/builds/{bid}/reference-images").status_code == 204
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["prototype_stale"]
    assert req.load(folder).invalidated
    assert "state: stale" in (folder / "docs/feasibility.md").read_text()


def test_reference_change_before_first_assessment(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    req.reference_changed(folder)
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["prototype_stale"]


def test_digest_covers_all_inputs(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    checker, ledger = capabilities.Checker(capabilities.load_registry()), req.Ledger()
    snapshot = req.inputs(app.state.db, bid, folder)
    before = req.input_digest(snapshot, ledger, checker)
    for key, value in (("reference", {"id": "ref_new"}), ("definitions", {"revenue": "net_sales"}),
                       ("sources", [{"columns": [{"name": "new", "type": "STRING"}]}]),
                       ("incoming", [{"id": "m_new", "text": "new request"}])):
        changed = copy.deepcopy(snapshot)
        changed[key] = value
        assert req.input_digest(changed, ledger, checker) != before
    changed = copy.deepcopy(snapshot)
    changed["spec"]["title"] = "new"
    assert req.input_digest(changed, ledger, checker) != before
    registry = checker.registry.model_copy(update={"registry_version": "1.1"})
    assert req.input_digest(snapshot, ledger, capabilities.Checker(registry)) != before
    assert req.input_digest(snapshot, ledger, capabilities.Checker(checker.registry, allowed={"bar"})) != before
    registry = checker.registry.model_dump(mode="json")
    registry["capabilities"][0]["label"] += "!"
    assert req.input_digest(snapshot, ledger, capabilities.Checker(capabilities.Registry.model_validate(registry))) != before


def test_spec_allowlist_and_schema_changes_get_stale_without_model(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    model = use_model(monkeypatch, app)
    check(client, app, bid)
    monkeypatch.setenv("DSS_ALLOWED_TYPES", "bar")
    assert client.get(f"/api/builds/{bid}/feasibility").json()["state"] == "stale"
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and any(i["status"] == "unsupported_app" for i in a["issues"])
    source(app, bid, new="STRING")
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale" and a["prototype_stale"]
    assert model.calls == 0


class Counted(Capture):
    counted: int = 0
    reported: int = 12001

    async def count_request_tokens(self, request):
        self.counted += 1
        return self.reported


@pytest.mark.parametrize("reported,generated,state", [(12000, 1, "ready"), (12001, 0, "blocked")])
def test_full_counted_input_budget(thin, monkeypatch, reported, generated, state):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show bar chart")
    model = Counted(response=json.dumps({"requirements": [extracted(sid)]}), reported=reported, requests=[])
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == state and model.calls == generated and model.counted == 1
    if state == "blocked":
        assert "Reduce" in a["issues"][0]["reason"]


def test_oversize_assembly_blocks_without_call(thin, monkeypatch):
    client, app, bid, folder = thin
    user(app, bid, "x" * 60000)
    model = use_model(monkeypatch, app)
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and model.calls == 0


@pytest.mark.parametrize("count,state", [(40, "ready"), (41, "blocked")])
def test_requirement_count_bound(thin, monkeypatch, count, state):
    client, app, bid, folder = thin
    sid = user(app, bid, "Many bars")
    model = use_model(monkeypatch, app, *[extracted(sid, text=f"Bar {i}") for i in range(count)])
    _, a = check(client, app, bid)
    assert a["state"] == state and model.calls == 1
    assert len(req.load(folder).requirements) <= 40


def test_issue_count_overflow_blocks_whole_scope(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Many unknowns")
    use_model(monkeypatch, app, *[extracted(sid, "unknown.feature", text=f"Unknown {i}") for i in range(21)])
    _, a = check(client, app, bid)
    assert a["state"] == "blocked" and len(a["issues"]) == 1
    assert "20 issues" in a["issues"][0]["reason"] and len(req.load(folder).requirements) == 21


def test_failed_extraction_preserves_ledger_and_artifacts(thin, monkeypatch):
    client, app, bid, folder = thin
    load(client, bid)
    use_model(monkeypatch, app)
    check(client, app, bid)
    user(app, bid, "new request")
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    model = FakeLLM(response="invalid JSON")
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: model)
    _, a = check(client, app, bid)
    assert a["state"] == "stale" and model.calls == 1
    assert all(p.read_bytes() == content for p, content in before.items())


def test_save_rollback(thin, monkeypatch):
    client, app, bid, folder = thin
    use_model(monkeypatch, app)
    check(client, app, bid)
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    real = Path.replace
    def fail(path, target):
        if path.name == "requirements.json.tmp":
            raise OSError("injected")
        return real(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        req.save(folder, req.load(folder), req.Assessment(state="blocked"))
    assert all(p.read_bytes() == content for p, content in before.items())


def test_busy_stage_missing_and_empty_body(thin, monkeypatch):
    client, app, bid, folder = thin
    use_model(monkeypatch, app)
    assert client.get("/api/builds/b_000000000000/feasibility").status_code == 404
    assert client.post(f"/api/builds/{bid}/feasibility/check", json={}).status_code == 422
    app.state.harness.active_builds.add(bid)
    assert client.post(f"/api/builds/{bid}/feasibility/check").status_code == 409
    app.state.harness.active_builds.discard(bid)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='done' WHERE id=?", (bid,))
    assert client.post(f"/api/builds/{bid}/feasibility/check").status_code == 409


def test_deterministic_bounded_recompute_speed():
    checker = capabilities.Checker(capabilities.load_registry())
    ledger = req.Ledger(requirements=[req.Requirement(id=f"r{i}", source=req.Source(id="m", kind="message", text="bar"),
        text=f"Bar {i}", needs=[capabilities.Need(capability="chart.bar")]) for i in range(40)])
    snapshot = {"sources": [], "incoming": [], "reference": None, "definitions": {}, "spec": {
        "pages": [{"components": [{"id": f"c{i}", "type": "bar"} for i in range(24)]}]}}
    start = time.perf_counter()
    a = req.evaluate(snapshot, ledger, checker)
    assert a.state == "ready" and time.perf_counter() - start < .1


def test_ledger_mandatory_and_no_rows(thin, monkeypatch):
    client, app, bid, folder = thin
    sid = user(app, bid, "Show bar")
    use_model(monkeypatch, app, extracted(sid))
    check(client, app, bid)
    section = requirement_sections(folder)[0]
    assert section.kind == "docs" and sid in section.body
    snapshot = req.inputs(app.state.db, bid, folder)
    assert not any(k in json.dumps(snapshot) for k in ("sample_rows", "api_key", "aggregate-cache"))


def test_comment_and_image_item_provenance_and_reference_removal(thin):
    client, app, bid, folder = thin
    folder.mkdir(parents=True)
    message = episodic.save(app.state.db, bid, "user", json.dumps([{"component_id": "p1_revenue", "text": "Use a bar"}]), "revise")
    record = {"id": "ref_one", "mode": "recreate", "instructions": "", "images": [{"id": "img_one"}],
              "interpretation": {"items": [{"id": "o1", "kind": "chart", "chart_candidate": "sankey", "label": "Flow"}]}}
    (folder / "references.json").write_text(json.dumps(record))
    snapshot = req.inputs(app.state.db, bid, folder)
    comment, image = snapshot["incoming"]
    assert comment["kind"] == "comment" and comment["id"] == message["id"] + ":0" and comment["component_id"] == "p1_revenue"
    assert image["kind"] == "image" and image["reference_id"] == "ref_one" and image["image_id"] == "img_one" and image["item_id"] == "o1"
    ledger = req.merge(req.Ledger(), snapshot, req.Extraction(requirements=[
        req.Extracted(**extracted(comment["id"])), req.Extracted(source_id=image["id"], text="Flow with sankey")]))
    assert len(ledger.requirements) == 2
    snapshot["reference"] = None
    snapshot["incoming"] = [comment]
    updated = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    assert len(updated.requirements) == 1 and updated.requirements[0].source.kind == "comment"


def test_plan_spec_revise_keep_ledger_as_mandatory_docs(thin, monkeypatch):
    from dss.harness.context import plan_context, spec_context, revise_context
    from test_context import spec_inputs
    client, app, bid, folder = thin
    load(client, bid)
    sid = user(app, bid, "Show bar chart")
    use_model(monkeypatch, app, extracted(sid))
    check(client, app, bid)
    _, build = spec_inputs(app, bid, "Revenue as a scorecard")
    config = app.state.settings.get()
    document = json.loads((folder / "spec.json").read_text())
    for context in (plan_context(app.state.db, config, bid), spec_context(config, folder, build, [], {"scorecard"}),
                    revise_context(document, [{"component_id": "p1_revenue", "text": "Blue"}], {"scorecard"}, config, folder=folder)):
        sections = [s for s in context.sections if s.name == "requirements.json"]
        assert len(sections) == 1 and sections[0].kind == "docs" and sid in sections[0].text
        assert sid in context.refit(lambda text: True)  # Mandatory even when all droppable memory is removed.
