"""api.md 3.4 `GET /api/hosting` and the open link's `403 source_locked` (task 29.3)."""
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dss.config import Config
from dss.data import research as scraper
from dss.harness.nodes import research
from dss.main import create_app
from fakes import fake_models
from test_intake import SALES, FakeBigQuery
from test_research import CSV, FakeSearch, ResearchLLM
from test_synthetic_api import FakeTypedBigQuery, generate

HOSTED = Path(__file__).resolve().parents[2] / "contracts/fixtures/hosted-build"
CODE = "c0de-c0de-c0de"


def fixture(name):
    return json.loads((HOSTED / name).read_text(encoding="utf-8"))


class Recorder:
    """Records every BigQuery/GCS service construction and method call."""
    def __init__(self, fake):
        self.fake, self.calls = fake, []

    def factory(self, config):
        self.calls.append("factory")
        return self

    def __getattr__(self, name):
        self.calls.append(name)
        return getattr(self.fake, name)


def open_config(tmp_path, **values):
    return Config(data_dir=tmp_path / "data", db_path=tmp_path / "local.sqlite", gcp_project_id="test-project",
                  cloud_service="dss", public_link="1", engine_mode="agent",
                  share_bucket="dss-share", share_dir=str(tmp_path / "share"), **values)


def create(client, mode="data"):
    response = client.post("/api/builds", json={"archetype": "executive", "mode": mode})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_local_mode_hosting(tmp_path):
    with TestClient(create_app(Config(data_dir=tmp_path), model_lister=fake_models)) as client:
        assert client.get("/api/hosting").json() == fixture("hosting.local.json")


def test_open_link_hosting(tmp_path):
    with TestClient(create_app(open_config(tmp_path), model_lister=fake_models)) as client:
        assert client.get("/api/hosting").json() == fixture("hosting.open.json")


@pytest.mark.parametrize("cloud, public", [("dss", ""), ("", "1")])
def test_agent_mode_without_open_link_locks_nothing(tmp_path, cloud, public):
    # DSS_PUBLIC counts only on Cloud Run (conventions.md 1.6); share data needs both names.
    config = Config(data_dir=tmp_path / "data", db_path=tmp_path / "local.sqlite", engine_mode="agent",
                    cloud_service=cloud, public_link=public, access_code="" if public else "x" * 12,
                    share_bucket="dss-share", share_dir=str(tmp_path / "share"))
    with TestClient(create_app(config, model_lister=fake_models)) as client:
        hosting = client.get("/api/hosting", headers={"X-DSS-Access-Code": "x" * 12}).json()
    assert hosting == {**fixture("hosting.open.json"), "public": False, "locked_sources": []}


def test_share_data_needs_agent_mode(tmp_path):
    config = Config(data_dir=tmp_path, share_bucket="dss-share", share_dir=str(tmp_path / "share"))
    with TestClient(create_app(config, model_lister=fake_models)) as client:
        assert client.get("/api/hosting").json()["share_data"] is False


def test_hosting_needs_the_access_code(tmp_path):
    config = Config(data_dir=tmp_path / "data", db_path=tmp_path / "local.sqlite", cloud_service="dss",
                    access_code=CODE * 2)
    with TestClient(create_app(config, model_lister=fake_models)) as client:
        response = client.get("/api/hosting")
        assert response.status_code == 401 and response.json()["error"]["code"] == "access_required"
        response = client.get("/api/hosting", headers={"X-DSS-Access-Code": CODE * 2})
        assert response.status_code == 200 and response.json()["public"] is False


@pytest.mark.parametrize("kind, uri", [("gcs", "gs://example-bucket/sales.csv"),
                                       ("bigquery", "other-project.dataset.existing"),
                                       ("gcs", "https://not-even-valid.example.com/x.csv")])
def test_open_link_locks_gcs_and_bigquery_before_any_read(tmp_path, kind, uri):
    recorder = Recorder(FakeBigQuery())
    app = create_app(open_config(tmp_path), model_lister=fake_models, bigquery_factory=recorder.factory)
    with TestClient(app) as client:
        bid = create(client)
        recorder.calls.clear()
        response = client.post(f"/api/builds/{bid}/sources", json={"kind": kind, "uri": uri})
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "source_locked"
        assert response.json()["error"]["detail"] == {"kind": kind}
        assert recorder.calls == [] and recorder.fake.loads == []
        assert client.get(f"/api/builds/{bid}").json()["sources"] == []
        assert client.post("/api/builds/missing/sources", json={"kind": kind, "uri": uri}).status_code == 404


def test_open_link_upload_still_succeeds(tmp_path):
    fake = FakeBigQuery()
    app = create_app(open_config(tmp_path), model_lister=fake_models, bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        bid = create(client)
        response = client.post(f"/api/builds/{bid}/sources/upload", files=[("files", ("sales.csv", SALES, "text/csv"))])
        assert response.status_code == 201, response.text
        assert [source["kind"] for source in response.json()["sources"]] == ["upload"] and len(fake.loads) == 1


def test_open_link_research_still_succeeds(tmp_path, monkeypatch):
    fake, model = FakeBigQuery(), ResearchLLM()
    monkeypatch.setattr(research, "google_search", FakeSearch())
    monkeypatch.setattr(scraper, "http_get", lambda url, timeout: (200, {"content-type": "text/csv"}, CSV))
    app = create_app(open_config(tmp_path, google_api_key="test-key"), model_lister=fake_models,
                     bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.harness.models, "llm_for", lambda _: model)
        bid = create(client, mode="research")
        response = client.post(f"/api/builds/{bid}/research", json={"prompt": "Player stats"})
        assert response.status_code == 202, response.text
        for _ in range(200):
            with app.state.db.connect() as conn:
                trace = conn.execute("SELECT status FROM traces WHERE run_id=?", (response.json()["run_id"],)).fetchone()
            if trace:
                break
            time.sleep(.02)
        assert trace and trace[0] == "ok" and len(fake.loads) == 1


def test_open_link_synthetic_still_succeeds(tmp_path, monkeypatch):
    fake = FakeTypedBigQuery()
    app = create_app(open_config(tmp_path), model_lister=fake_models, bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        bid = create(client)
        _, status = generate(client, app, bid)
        assert status["state"] == "succeeded" and len(fake.loads) == 1
