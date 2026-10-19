"""Live interview-to-prototype path through the unmodified API (real Gemini and BigQuery)."""
import json
import os
import struct
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dss.config import BACKEND_DIR, Config
from dss.data.bigquery import BigQuery
from dss.main import create_app

SAMPLE = Path(__file__).parents[1] / "data/small_sales.csv"
EVIDENCE = BACKEND_DIR / ".blueprint/qa/final-audit/task-9.1"


def wait(app, seconds=300):
    deadline = time.monotonic() + seconds
    while app.state.engine_tasks or app.state.harness.active_builds:
        assert time.monotonic() < deadline, "agent run did not finish in time"
        time.sleep(.25)


def trace(app, run_id):
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE run_id=?", (run_id,)).fetchone()
    assert row is not None, run_id
    return dict(row)


@pytest.mark.live
def test_interview_to_prototype(tmp_path):
    env = Config.from_env()
    assert env.google_api_key.get_secret_value(), "GOOGLE_API_KEY must be configured for this live check"
    # DSS_LIVE_GCP_PROJECT overrides the root .env without editing it.
    project = (os.environ.get("DSS_LIVE_GCP_PROJECT") or env.gcp_project_id).strip()
    assert project, "Set GCP_PROJECT_ID or DSS_LIVE_GCP_PROJECT to an authorized project ID"
    config = env.model_copy(update={"data_dir": tmp_path / "data", "db_path": None, "static_dir": None,
        "access_code": SecretStr(""), "engine_mode": "local", "cloud_service": ""})
    app = create_app(config)
    runs = {}
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"gcp_project_id": project}).status_code == 200
        build = client.post("/api/builds", json={"title": "Live sales", "archetype": "executive", "mode": "data"}).json()
        build_id = build["id"]
        upload = client.post(f"/api/builds/{build_id}/sources/upload",
                             files=[("files", (SAMPLE.name, SAMPLE.read_bytes(), "text/csv"))])
        assert upload.status_code == 201, upload.text

        started = client.post(f"/api/builds/{build_id}/interview/start")
        assert started.status_code == 202, started.text
        runs["interview_start"] = started.json()["run_id"]
        wait(app)
        answer = client.post(f"/api/builds/{build_id}/messages", json={"text":
            "The regional sales director reviews revenue weekly: total revenue, revenue by region and "
            "the daily revenue trend. That is everything; please plan the dashboard."})
        assert answer.status_code == 202, answer.text
        runs["interview_answer"] = answer.json()["run_id"]
        wait(app)
        messages = client.get(f"/api/builds/{build_id}/messages").json()
        assert [m["role"] for m in messages].count("assistant") == 2
        for name in ("interview_start", "interview_answer"):
            assert trace(app, runs[name])["status"] == "ok"

        planned = client.post(f"/api/builds/{build_id}/plan")
        assert planned.status_code == 202, planned.text
        runs["plan"] = planned.json()["run_id"]
        wait(app, 600)
        plan_trace = trace(app, runs["plan"])
        assert plan_trace["status"] == "ok", plan_trace["error"]
        assert client.get(f"/api/builds/{build_id}").json()["stage"] == "prototype"
        nodes = [span["node"] for span in json.loads(plan_trace["spans_json"])]
        assert nodes[:3] == ["router", "plan", "view"]
        assert 1 <= sum(node in ("spec", "spec_repair") for node in nodes) <= 2, nodes
        assert nodes.index("render") > nodes.index("validate")

        folder = config.data_dir / "builds" / build_id / "v1"
        view = yaml.safe_load((folder / "docs/derived-fields.md").read_text(encoding="utf-8").split("---", 2)[1])["view"]
        rows = BigQuery(app.state.settings.get()).aggregate(f"SELECT * FROM `{view}` LIMIT 10")
        assert rows, "view SELECT returned no rows"

        background = client.get(f"/api/builds/{build_id}/files/background_p1.png")
        assert background.status_code == 200
        assert struct.unpack(">II", background.content[16:24])[0] == 1200
        html = client.get(f"/api/builds/{build_id}/prototype").text
        spec = client.get(f"/api/builds/{build_id}/spec").json()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": spec["canvas"]["width"], "height": spec["canvas"]["height"]})
            page.set_content(html, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(EVIDENCE / "prototype.png"), full_page=True)
        finally:
            browser.close()
    (EVIDENCE / "background_p1.png").write_bytes(background.content)
    (EVIDENCE / "runs.json").write_text(json.dumps({"build_id": build_id, "runs": runs, "plan_nodes": nodes,
        "plan_tokens": [plan_trace["input_tokens"], plan_trace["output_tokens"]], "view_rows": len(rows)}, indent=2))
    print(json.dumps({"build_id": build_id, "runs": runs, "plan_nodes": nodes, "view_rows": len(rows)}))
