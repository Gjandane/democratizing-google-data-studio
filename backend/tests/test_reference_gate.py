"""Task 26.3: the reference analysis approval gate (dashboard-intent.md 1.3, oracle 12).

Recreate sets come from the 26.2 analysis fixture (tests/data/reference_analysis_electricity.json),
committed by code without a model call; every route here is code only.
"""
import json
from pathlib import Path

import pytest

from dss.db import now
from dss.spec import references
from dss.spec import requirements as req
from test_audit_style import drain
from test_blueprint import blueprint_api  # noqa: F401 (fixture)
from test_context_node import context_api  # noqa: F401 (fixture)
from test_references import png
from test_thin_slice import thin  # noqa: F401 (fixture)

FIXTURE = json.loads((Path(__file__).parent / "data/reference_analysis_electricity.json").read_text(encoding="utf-8"))
INTENT = Path(__file__).resolve().parents[2] / "contracts/fixtures/dashboard-intent"
CONFIRMED = json.dumps({"context": "confirmed", "outline": "confirmed", "design": "confirmed", "blueprint": "confirmed"})
GATED = ("design/confirm", "blueprint/regenerate", "blueprint/accept", "recipe", "run")


def reference_set(folder, mode="recreate", analysis=True):
    """Commit the electricity set: a pending revision-1 analysis, a pre-1.3 `null` one, or style mode."""
    reply = FIXTURE["reply"]
    image = {"id": "img_0123456789ab", "name": "electricity.png", "file": "reference_img_0123456789ab.png",
             "mime_type": "image/png", "width": 160, "height": 100, "content": png(160, 100)}
    interpretation = references.interpret(mode, 160, 100, {k: reply[k] for k in ("palette_notes", "type_notes", "spacing_notes")})
    answers = [references.AnalysisAnswer.model_validate(item) for item in reply["items"]]
    result = references.analyze(answers, list(references.TYPES)) if mode == "recreate" and analysis else None
    record = {"id": "ref_0123456789ab", "mode": mode, "instructions": FIXTURE["instructions"] if mode == "recreate" else "",
              "images": [references.image_entry(image)],
              "summary": references.summary(interpretation, reply["style"]["palette"], 1, result),
              "style": reply["style"], "interpretation": interpretation.model_dump(),
              "analysis": result.model_dump() if result else None, "created_at": now()}
    (folder / "docs").mkdir(parents=True, exist_ok=True)
    references.commit(folder, record, [image], {"reference.md": references.reference_doc(record)})
    return record


def url(bid, path=""):
    return f"/api/builds/{bid}/reference-images/analysis{path}"


def choices(analysis, **changes):
    """The PUT items for `analysis` with {label: (disposition, type)} changes."""
    return [{"id": i["id"], **dict(zip(("disposition", "type"), changes.get(i["label"], (i["disposition"], i["type"]))))}
            for i in analysis["items"]]


def static_split(client, bid, note=""):
    """Edit every item to static art: since 26.4 approved native items need Blueprint rows, which these
    gate tests' fakes and staged builds don't plan (fulfilment is tested in test_render)."""
    analysis = client.get(f"/api/builds/{bid}/reference-images").json()["analysis"]
    items = [{"id": i["id"], "disposition": "static", "type": None} for i in analysis["items"]]
    response = client.put(url(bid), json={"revision": analysis["revision"], "items": items, "note": note})
    assert response.status_code == 200, response.text


def approve(client, bid):
    analysis = client.get(f"/api/builds/{bid}/reference-images").json()["analysis"]
    response = client.post(url(bid, "/approve"), json={"revision": analysis["revision"]})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["state"] == "approved"
    return response.json()


def unapproved(response):
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "reference_unapproved"
    assert response.json()["error"]["detail"] == {"reference_set_id": "ref_0123456789ab"}


def files(folder):
    return {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def allowed(monkeypatch):
    monkeypatch.setenv("DSS_ALLOWED_TYPES", ",".join(references.TYPES))  # the root .env may narrow it


@pytest.fixture
def staged(thin, allowed):
    """A 2.0 prototype build (every artifact confirmed) with a spec and no assessment yet."""
    from test_thin_slice import load
    client, app, bid, folder = thin
    load(client, bid)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET artifacts_json=? WHERE id=?", (CONFIRMED, bid))
    return client, app, bid, folder


def test_design_and_blueprint_routes_refuse_until_approved(blueprint_api, allowed):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    from test_blueprint import confirm
    from test_context_node import wait
    reference_set(folder)
    before, sql = files(folder), list(bq.sql)
    unapproved(client.post(f"/api/builds/{bid}/design/confirm"))
    # Code only and first: no model call, no view SQL, no file or stage change, lock released.
    assert llm.calls == 0 and bq.sql == sql and files(folder) == before
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "design" and not app.state.harness.active_builds
    static_split(client, bid)
    approve(client, bid)
    confirm(client, app, bid)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "blueprint" and llm.calls >= 1
    # An edit after approval re-gates and marks the saved Blueprint stale.
    static_split(client, bid, note="Keep the selector as art.")
    assert client.get(f"/api/builds/{bid}").json()["artifacts"]["blueprint"] == "stale"
    calls, before = llm.calls, files(folder)
    for route in ("blueprint/regenerate", "blueprint/accept"):
        unapproved(client.post(f"/api/builds/{bid}/{route}"))
    assert llm.calls == calls and files(folder) == before
    assert client.get(f"/api/builds/{bid}").json()["artifacts"]["blueprint"] == "stale"
    approve(client, bid)
    llm.replies.append(json.dumps(value))
    regenerated = client.post(f"/api/builds/{bid}/blueprint/regenerate")
    assert regenerated.status_code == 202, regenerated.text
    wait(app)
    assert client.get(f"/api/builds/{bid}").json()["artifacts"]["blueprint"] == "draft"
    accepted = client.post(f"/api/builds/{bid}/blueprint/accept")
    assert accepted.json().get("error", {}).get("code") != "reference_unapproved", accepted.text
    wait(app)


@pytest.mark.parametrize("analysis", [True, False], ids=["pending", "pre_1_3_null"])
def test_recipe_and_run_refuse_until_approved(staged, monkeypatch, analysis):
    from dss.api import run
    from test_feasibility import check, use_model
    client, app, bid, folder = staged
    reference_set(folder, analysis=analysis)
    (folder / "recipe.jsonl").write_bytes(b"previous complete recipe\n")
    before = files(folder)

    def refuse(*args, **kwargs):
        pytest.fail("a gated request reached compilation or job preparation")
    with monkeypatch.context() as patch:
        patch.setattr(run, "compile_recipe", refuse)
        patch.setattr(run, "compile_current", refuse)
        patch.setattr(app.state.agent_jobs, "prepare", refuse)
        for route in ("recipe", "run"):
            unapproved(client.post(f"/api/builds/{bid}/{route}"))
    assert files(folder) == before and not app.state.engine_busy and not app.state.harness.active_builds
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "prototype"
    if not analysis:  # a pre-1.3 set has nothing to approve: re-upload to analyze
        response = client.post(url(bid, "/approve"), json={"revision": 1})
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
        return
    static_split(client, bid)
    approve(client, bid)
    model = use_model(monkeypatch, app)
    _, assessment = check(client, app, bid)
    assert assessment["state"] == "ready" and not assessment["prototype_stale"], assessment
    recipe = client.post(f"/api/builds/{bid}/recipe")
    assert recipe.status_code == 200, recipe.text
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    client.portal.call(drain, app)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "done" and model.calls == 0


def test_edit_after_approval_is_a_reference_change(staged, monkeypatch):
    from test_feasibility import check, use_model
    client, app, bid, folder = staged
    reference_set(folder)
    approve(client, bid)
    use_model(monkeypatch, app)
    _, assessment = check(client, app, bid)
    assert assessment["state"] == "ready" and not assessment["prototype_stale"]
    # Re-approving the same revision changes nothing (idempotent, no write).
    before = files(folder)
    again = approve(client, bid)
    assert files(folder) == before and again == client.get(f"/api/builds/{bid}/reference-images").json()
    assert client.get(f"/api/builds/{bid}/feasibility").json()["state"] == "ready"
    analysis = again["analysis"]
    edited = client.put(url(bid), json={"revision": analysis["revision"], "items": choices(analysis), "note": "Same split."})
    assert edited.status_code == 200 and edited.json()["analysis"]["state"] == "pending"
    assessment = client.get(f"/api/builds/{bid}/feasibility").json()
    assert assessment["state"] == "stale" and assessment["prototype_stale"]
    build = client.get(f"/api/builds/{bid}").json()
    assert build["artifacts"]["blueprint"] == "stale" and build["stage"] == "prototype"
    assert req.load(folder).prototype_stale and req.load(folder).invalidated
    unapproved(client.post(f"/api/builds/{bid}/recipe"))
    # Approving again does not authorize the old prototype: replanning is explicit.
    approve(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").json()["error"]["code"] in ("wrong_stage", "feasibility_blocked")


def test_editing_a_pending_analysis_is_no_reference_change(staged):
    client, app, bid, folder = staged
    reference_set(folder)
    analysis = client.get(f"/api/builds/{bid}/reference-images").json()["analysis"]
    response = client.put(url(bid), json={"revision": 1, "items": choices(analysis), "note": ""})
    assert response.status_code == 200 and response.json()["analysis"]["revision"] == 2
    assert client.get(f"/api/builds/{bid}").json()["artifacts"]["blueprint"] == "confirmed"
    assert not req.load(folder).invalidated


def test_put_validates_the_split_and_fills_issues(staged):
    client, app, bid, folder = staged
    record = reference_set(folder)
    analysis = client.get(f"/api/builds/{bid}/reference-images").json()["analysis"]
    items = choices(analysis)
    for bad in ({"revision": 1, "items": items[1:], "note": ""},  # an id missing
                {"revision": 1, "items": [*items, items[0]], "note": ""},  # an id twice
                {"revision": 1, "items": [*items[1:], {**items[0], "id": "r99"}], "note": ""},  # unknown id
                {"revision": 1, "items": [{**items[0], "label": "x"}, *items[1:]], "note": ""},  # read-only field
                {"revision": "1", "items": items, "note": ""},
                {"revision": 1, "items": items, "note": "x" * 1001}):
        response = client.put(url(bid), json=bad)
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request", bad
    assert references.load(folder) == record
    labels = {i["label"]: n for n, i in enumerate(analysis["items"])}
    response = client.put(url(bid), json={"revision": 1, "note": "Keep the globe as art.", "items": choices(analysis, **{
        "People without access to electricity": ("static", "bar"),  # static drops its type
        "Rural and urban access by country": ("native", "sankey"),  # not an allowed type
        "Region Selector": ("native", "bar"),  # a control needs a control type
        "Location Rural Urban legend": ("native", "dropdown")})})  # a control type on a non-control
    assert response.status_code == 200, response.text
    result = response.json()["analysis"]
    assert (result["revision"], result["state"], result["note"]) == (2, "pending", "Keep the globe as art.")
    assert result["items"][labels["People without access to electricity"]]["type"] is None
    assert [i["path"] for i in result["issues"]] == sorted(
        (f"/items/{labels[name]}/type" for name in ("Rural and urban access by country", "Region Selector",
                                                     "Location Rural Urban legend")), key=lambda p: int(p.split("/")[2]))
    for before, after in zip(analysis["items"], result["items"]):  # read-only fields never change
        assert {k: v for k, v in before.items() if k not in ("disposition", "type")} == \
               {k: v for k, v in after.items() if k not in ("disposition", "type")}
    assert result["summary"] == references.analysis_summary(references.ReferenceAnalysis.model_validate(result).items)
    assert response.json()["summary"].endswith(result["summary"])
    reference_md = (folder / "docs/reference.md").read_text(encoding="utf-8")
    assert "(revision 2, pending)" in reference_md and "Keep the globe as art." in reference_md
    # Approve needs no issues, then the current revision.
    blocked = client.post(url(bid, "/approve"), json={"revision": 2})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "artifact_invalid"
    assert [i["path"] for i in blocked.json()["error"]["detail"]["issues"]] == [i["path"] for i in result["issues"]]
    for stale in (client.post(url(bid, "/approve"), json={"revision": 1}),
                  client.put(url(bid), json={"revision": 1, "items": items, "note": ""})):
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "reference_analysis_conflict"
        assert stale.json()["error"]["detail"] == {"revision": 2}
    fixed = client.put(url(bid), json={"revision": 2, "items": items, "note": ""})
    assert fixed.json()["analysis"]["issues"] == [] and fixed.json()["analysis"]["revision"] == 3
    approved = approve(client, bid)
    assert approved["analysis"]["revision"] == 3
    assert client.post(url(bid, "/approve"), json={"revision": 3}).json() == approved


def test_responses_match_the_contract_fixtures(staged):
    from test_api_contract import shape
    client, app, bid, folder = staged
    reference_set(folder)
    analysis = client.get(f"/api/builds/{bid}/reference-images").json()["analysis"]
    pending = client.put(url(bid), json={"revision": 1, "items": choices(analysis), "note": "n"}).json()
    for got, name in ((pending, "reference_set.pending.json"), (approve(client, bid), "reference_set.json")):
        expected = json.loads((INTENT / name).read_text(encoding="utf-8"))
        references.ReferenceAnalysis.model_validate(got["analysis"])
        # Item types are nullable (static): compare item keys, and every other field by type.
        shape({**got, "analysis": {**got["analysis"], "items": []}}, {**expected, "analysis": {**expected["analysis"], "items": []}})
        assert all(item.keys() == expected["analysis"]["items"][0].keys() for item in got["analysis"]["items"])


def test_narrowed_allowed_types_reopen_the_gate(staged, monkeypatch):
    client, app, bid, folder = staged
    reference_set(folder)
    approve(client, bid)
    monkeypatch.setenv("DSS_ALLOWED_TYPES", ",".join(t for t in references.TYPES if t != "area"))
    analysis = client.get(f"/api/builds/{bid}/reference-images").json()["analysis"]
    area = next(n for n, i in enumerate(analysis["items"]) if i["type"] == "area")
    assert analysis["state"] == "pending" and "area" not in analysis["allowed_types"]
    assert analysis["issues"] == [{"path": f"/items/{area}/type", "message": "Type is not one of the allowed types"}]
    assert references.load(folder)["analysis"]["state"] == "approved"  # a read never writes
    unapproved(client.post(f"/api/builds/{bid}/recipe"))
    blocked = client.post(url(bid, "/approve"), json={"revision": analysis["revision"]})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "artifact_invalid"
    label = analysis["items"][area]["label"]
    response = client.put(url(bid), json={"revision": analysis["revision"], "items": choices(
        analysis, **{label: ("native", "time_series")}), "note": ""})
    assert response.json()["analysis"]["issues"] == []
    approve(client, bid)
    assert client.post(f"/api/builds/{bid}/recipe").json()["error"]["code"] != "reference_unapproved"


@pytest.mark.parametrize("mode", ["style", None])
def test_style_sets_and_builds_without_a_set_are_never_gated(staged, monkeypatch, mode):
    from test_feasibility import check, use_model
    client, app, bid, folder = staged
    if mode:
        reference_set(folder, mode="style")
        assert client.get(f"/api/builds/{bid}/reference-images").json()["analysis"] is None
    for path, body in (("", {"revision": 1, "items": [{"id": "r1", "disposition": "static", "type": None}], "note": ""}),
                       ("/approve", {"revision": 1})):
        response = client.request("PUT" if not path else "POST", url(bid, path), json=body)
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    use_model(monkeypatch, app)
    check(client, app, bid)
    response = client.post(f"/api/builds/{bid}/recipe")
    assert response.status_code == 200, response.text


def test_a_pre_2_0_build_recipe_is_not_gated(thin, allowed, monkeypatch):
    from test_feasibility import check, use_model
    from test_thin_slice import load
    client, app, bid, folder = thin
    load(client, bid)  # legacy: no staged artifacts, only a spec
    reference_set(folder)
    use_model(monkeypatch, app)
    check(client, app, bid)
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200


@pytest.mark.parametrize("value", ["build", "done"])
def test_edits_need_connect_through_prototype(staged, value):
    client, app, bid, folder = staged
    record = reference_set(folder)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage=? WHERE id=?", (value, bid))
    items = choices(record["analysis"])
    for response in (client.put(url(bid), json={"revision": 1, "items": items, "note": ""}),
                     client.post(url(bid, "/approve"), json={"revision": 1})):
        assert response.status_code == 409 and response.json()["error"] == {
            "code": "wrong_stage", "message": response.json()["error"]["message"], "detail": {"stage": value}}
    assert references.load(folder) == record


def test_edits_wait_for_a_running_action(staged):
    client, app, bid, folder = staged
    record = reference_set(folder)
    app.state.harness.active_builds.add(bid)
    try:
        response = client.post(url(bid, "/approve"), json={"revision": 1})
        assert response.status_code == 409 and response.json()["error"]["code"] == "wrong_stage"
    finally:
        app.state.harness.active_builds.discard(bid)
    assert references.load(folder) == record


@pytest.mark.parametrize("mode", ["null", "style", "none"])
def test_design_confirm_gates_a_null_set_but_never_style_or_no_set(blueprint_api, allowed, mode):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    from test_context_node import wait
    if mode != "none":
        reference_set(folder, mode="style" if mode == "style" else "recreate", analysis=False)
    response = client.post(f"/api/builds/{bid}/design/confirm")
    if mode == "null":
        unapproved(response)
        assert llm.calls == 0 and client.get(f"/api/builds/{bid}").json()["stage"] == "design"
        # Reach the blueprint stage under a style set, then the pre-1.3 set gates both blueprint routes.
        reference_set(folder, mode="style")
        assert client.post(f"/api/builds/{bid}/design/confirm").status_code == 202
        wait(app)
        reference_set(folder, analysis=False)
        calls = llm.calls
        for route in ("blueprint/regenerate", "blueprint/accept"):
            unapproved(client.post(f"/api/builds/{bid}/{route}"))
        assert llm.calls == calls and client.get(f"/api/builds/{bid}").json()["stage"] == "blueprint"
    else:
        assert response.status_code == 202, response.text
        wait(app)
