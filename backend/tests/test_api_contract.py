"""Contract shapes for endpoints implemented through phase 4; later phases add theirs."""
import json
from pathlib import Path
from test_thin_slice import thin, load
from test_execute import settle
from test_recipe_contract import agent_client, no_engine, spec

FIXTURES = Path(__file__).resolve().parents[2] / "contracts/fixtures/api"
NULLABLE = {"spec_version": int, "report_url": str, "node": str, "model": str, "error": str, "build_id": str, "agent_last_seen": str}


def shape(actual, expected, field=""):
    if field in NULLABLE and not isinstance(expected, dict):
        assert actual is None or type(actual) is NULLABLE[field]
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key in expected:
            shape(actual[key], expected[key], key)
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        for item in actual:
            shape(item, expected[0])
    else:
        assert type(actual) is type(expected)


def check(response, fixture, status=200):
    assert response.status_code == status, response.text
    shape(response.json(), json.loads((FIXTURES / fixture).read_text()))


def test_phase4_contract(thin):
    client, app, bid, folder = thin
    assert client.get("/api/health").json() == {"status":"ok"}
    check(client.get(f"/api/builds/{bid}"), "build.json")
    check(client.get("/api/builds"), "builds.json")
    check(client.get("/api/settings"), "settings.json")
    check(client.put("/api/settings", json={"bq_location":"US"}), "settings.json")
    check(client.get(f"/api/builds/{bid}/messages"), "messages.json")
    check(client.post(f"/api/builds/{bid}/run"), "error.json", 409)
    load(client, bid)
    check(client.post(f"/api/builds/{bid}/recipe"), "recipe.json")
    assert client.get(f"/api/builds/{bid}/spec").json() == json.loads((folder / "spec.json").read_text())
    assert "dss-canvas" in client.get(f"/api/builds/{bid}/prototype").text
    (folder / "docs").mkdir(exist_ok=True)
    (folder / "docs/example.md").write_text("---\ntype: Example\n---\nHello")
    assert client.get(f"/api/builds/{bid}/docs/example.md").text.endswith("Hello")
    (folder / "background_p1.png").write_bytes(b"image")
    assert client.get(f"/api/builds/{bid}/files/background_p1.png").content == b"image"
    assert client.get(f"/api/builds/{bid}/files/%2e%2e").status_code in (400,404)
    check(client.post(f"/api/builds/{bid}/run"), "run_accepted.json", 202)
    settle(client, app)
    check(client.get(f"/api/builds/{bid}"), "build.done.json")
    check(client.post(f"/api/builds/{bid}/versions"), "build.json", 201)
    check(client.get("/api/engine/status"), "engine_status.local.json")
    check(client.post("/api/engine/login"), "run_accepted.json", 202)
    settle(client, app)
    check(client.get("/api/traces"), "traces.json")
    check(client.get(f"/api/traces?build_id={bid}"), "traces.json")


def test_recipe_contract_in_agent_mode_without_engine(agent_client, spec):
    client, app, folder = agent_client
    (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    check(client.post(f"/api/builds/{spec.build_id}/recipe"), "recipe.json")


def test_intake_and_action_contracts(thin, monkeypatch):
    import time
    from fakes import FakeLLM
    from test_intake import FakeBigQuery, SALES
    client, app, bid, folder = thin
    app.state.settings.update({"gcp_project_id":"test-project"})
    fake = FakeBigQuery()
    app.state.bigquery_factory = lambda _: fake
    upload = client.post(f"/api/builds/{bid}/sources/upload", files=[("files", ("sales.csv", SALES, "text/csv"))])
    assert upload.status_code == 201, upload.text
    source_shape = json.loads((FIXTURES / "build.json").read_text())["sources"][0]
    shape(upload.json(), {"sources":[source_shape]})
    for body in ({"kind":"gcs", "uri":"gs://example-bucket/sales.csv"},
                 {"kind":"bigquery", "uri":upload.json()["sources"][0]["bq_table"]}):
        response = client.post(f"/api/builds/{bid}/sources", json=body)
        assert response.status_code == 201, response.text
        shape(response.json(), source_shape)
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: FakeLLM(response="What decision matters most?"))
    def finish():
        for _ in range(500):
            if not app.state.engine_tasks:
                return
            time.sleep(.01)
        raise AssertionError("Action did not finish")
    check(client.post(f"/api/builds/{bid}/interview/start"), "run_accepted.json", 202)
    finish()
    response = client.post(f"/api/builds/{bid}/messages", json={"text":"Compare regional revenue"})
    assert response.status_code == 202
    shape(response.json(), {"run_id":"r", "message_id":"m"})
    finish()
    check(client.get(f"/api/builds/{bid}/messages"), "messages.json")
    # Invalid fake planner output still exercises the accepted-action response without a provider.
    check(client.post(f"/api/builds/{bid}/plan"), "run_accepted.json", 202)
    finish()
    load(client, bid)
    component = client.get(f"/api/builds/{bid}/spec").json()["pages"][0]["components"][0]["id"]
    check(client.post(f"/api/builds/{bid}/comments", json={"comments":[{"component_id":component,"text":"Make it blue"}]}), "run_accepted.json", 202)
    finish()


INTENT = Path(__file__).resolve().parents[2] / "contracts/fixtures/dashboard-intent"


def test_reference_set_contract(thin, monkeypatch):
    """dashboard-intent.md Reference set: exact ReferenceSet keys/types, 202/204, legacy alias, errors."""
    from fakes import FakeLLM
    from dss.spec import references
    from test_audit_style import drain
    from test_references import output, png
    client, app, bid, folder = thin
    monkeypatch.setattr(references, "decode", lambda images: None)
    monkeypatch.setattr(app.state.models, "llm_for", lambda _: FakeLLM(response=output()))
    fixture = json.loads((INTENT / "reference_set.json").read_text())
    response = client.get(f"/api/builds/{bid}/reference-images")
    assert response.status_code == 200 and response.json() is None
    for path, data in (("reference-images", {"mode": "recreate", "instructions": "Use net sales for Revenue."}),
                       ("style-images", {})):
        check(client.post(f"/api/builds/{bid}/{path}", files=[("files", ("a.png", png(), "image/png"))], data=data),
              "run_accepted.json", 202)
        client.portal.call(drain, app)
        result = client.get(f"/api/builds/{bid}/reference-images")
        check(result, "../dashboard-intent/reference_set.json")
        assert result.json()["images"][0]["file"].startswith("reference_img_")
    for content, name, kind, status in ((png() + b"0" * references.MAX_FILE_BYTES, "a.png", "image/png", 413),
                                        (b"text", "a.txt", "text/plain", 422)):
        error = client.post(f"/api/builds/{bid}/reference-images", data={"mode": "recreate"}, files=[("files", (name, content, kind))])
        # error.json's detail is wrong_stage's; upload errors carry detail.reason (existing invalid_source code).
        assert error.status_code == status and error.json()["error"].keys() == {"code", "message", "detail"}
        assert error.json()["error"]["code"] == "invalid_source" and isinstance(error.json()["error"]["detail"]["reason"], str)
    deleted = client.delete(f"/api/builds/{bid}/reference-images")
    assert deleted.status_code == 204 and client.get(f"/api/builds/{bid}/reference-images").json() is None
    assert fixture.keys() == {"id", "mode", "instructions", "images", "summary"}


def test_feasibility_contract_states(thin, monkeypatch):
    """Load the shared fixture explicitly; verify exact shape in every 11.3 state."""
    from dss.spec import requirements as req
    from test_feasibility import check as assess, user, use_model, extracted
    client, app, bid, folder = thin
    fixture = json.loads((INTENT / "feasibility.json").read_text())
    def conform(actual):
        req.Assessment.model_validate(actual)
        expected = {**fixture, "id": actual["id"], "input_digest": actual["input_digest"]}
        shape(actual, expected)
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "unchecked"
    conform(a)
    use_model(monkeypatch, app)
    _, a = assess(client, app, bid)
    assert a["state"] == "ready"
    conform(a)
    sid = user(app, bid, "Animate GPS points along a route")
    a = client.get(f"/api/builds/{bid}/feasibility").json()
    assert a["state"] == "stale"
    conform(a)
    use_model(monkeypatch, app, extracted(sid, "animation.temporal_playback"))
    _, a = assess(client, app, bid)
    assert a["state"] == "blocked" and a["issues"]
    conform(a)
