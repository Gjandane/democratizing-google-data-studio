"""Live typed synthetic intake through the unmodified API (real BigQuery; no model call)."""
import os
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dss.config import Config
from dss.data.bigquery import BigQuery
from dss.main import create_app


def column(name, kind, generator, nullable=0):
    return {"name": name, "type": kind, "nullable_fraction": nullable, "generator": generator}


# One all-null column per type, a string ID column with leading zeros, and all-empty records.
MIXED = {"schema_version": 1, "row_count": 300, "seed": 11, "columns": [
    column("code", "string", {"kind": "choice", "values": ["001", "010"]}, nullable=.4),
    column("units", "integer", {"kind": "integer", "min": 1, "max": 9}, nullable=.4),
    column("empty_amount", "number", {"kind": "decimal", "min": 0, "max": 5, "decimals": 2}, nullable=1),
    column("empty_day", "date", {"kind": "date", "start": "2026-01-01", "end": "2026-12-31"}, nullable=1),
    column("empty_flag", "boolean", {"kind": "boolean", "true_probability": .5}, nullable=1)]}
# A single column whose every value is null: csv.writer writes each record as `""`.
SINGLE = {"schema_version": 1, "row_count": 40, "seed": 2,
          "columns": [column("only", "integer", {"kind": "integer", "min": 0, "max": 1}, nullable=1)]}


def wait(app, seconds=300):
    deadline = time.monotonic() + seconds
    while app.state.engine_tasks or app.state.harness.active_builds:
        assert time.monotonic() < deadline, "generation did not finish in time"
        time.sleep(.25)


@pytest.mark.live
def test_synthetic_typed_load(tmp_path):
    env = Config.from_env()
    project = (os.environ.get("DSS_LIVE_GCP_PROJECT") or env.gcp_project_id).strip()
    assert project, "Set GCP_PROJECT_ID or DSS_LIVE_GCP_PROJECT to an authorized project ID"
    config = env.model_copy(update={"data_dir": tmp_path / "data", "db_path": None, "static_dir": None,
        "access_code": SecretStr(""), "engine_mode": "local", "cloud_service": ""})
    app = create_app(config)
    tables = []
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"gcp_project_id": project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        try:
            for spec, types in ((MIXED, ["STRING", "INTEGER", "NUMERIC", "DATE", "BOOLEAN"]), (SINGLE, ["INTEGER"])):
                build_id = client.post("/api/builds", json={"archetype": "executive", "mode": "data"}).json()["id"]
                response = client.post(f"/api/builds/{build_id}/synthetic-data",
                                       json={"generation_key": "live_1", "proposal_id": None, "spec": spec})
                assert response.status_code == 202, response.text
                wait(app)
                status = client.get(f"/api/builds/{build_id}/synthetic-data/jobs/live_1").json()
                assert status["state"] == "succeeded", status
                [source] = client.get(f"/api/builds/{build_id}").json()["sources"]
                tables.append(source["bq_table"])
                assert source["kind"] == "synthetic" and source["row_count"] == spec["row_count"]
                table = service.client.get_table(source["bq_table"])
                assert [(f.name, f.field_type) for f in table.schema] == list(zip([c["name"] for c in spec["columns"]], types))
                assert table.num_rows == spec["row_count"]
                lines = client.get(f"/api/builds/{build_id}/synthetic-data/{source['id']}/csv").text.split("\n")[1:-1]
                assert len(lines) == spec["row_count"]
                names = [c["name"] for c in spec["columns"]]
                every_null = " AND ".join(f"`{n}` IS NULL" for n in names)
                [row] = service.client.query(
                    f"SELECT COUNT(*) AS total, COUNTIF({every_null}) AS empty_rows"
                    + (", COUNTIF(code = '001') AS ids, COUNTIF(empty_amount IS NOT NULL OR empty_day IS NOT NULL "
                       "OR empty_flag IS NOT NULL) AS filled" if spec is MIXED else "")
                    + f" FROM `{source['bq_table']}`").result(timeout=120)
                assert row["total"] == spec["row_count"]
                expected_empty = sum(line in (",,,,", '""') for line in lines)
                assert row["empty_rows"] == expected_empty > 0
                if spec is MIXED:
                    assert row["ids"] == sum(line.startswith("001,") for line in lines) > 0 and row["filled"] == 0
        finally:
            for table in tables:
                service.client.delete_table(table, not_found_ok=True)
