"""Synthetic generation API, typed intake and download with fake BigQuery and no model call."""
import csv
import io
import json
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from fastapi.testclient import TestClient

from dss.config import Config
from dss.data import bigquery as data
from dss.data import synthetic
from dss.db import now
from dss.harness.nodes import synthetic_generate as node
from dss.main import create_app
from fakes import fake_models

FIXTURES = Path(__file__).resolve().parents[2] / "contracts/fixtures/synthetic-data"
REQUEST = json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))
SPEC = REQUEST["spec"]
PARSE = {"INTEGER": int, "NUMERIC": Decimal, "STRING": str, "DATE": date.fromisoformat,
         "BOOLEAN": lambda v: {"true": True, "false": False}[v]}


class FakeTypedBigQuery:
    """BigQuery CSV semantics for a declared schema: the empty field is NULL; typed parse otherwise."""
    def __init__(self, drop=0, fail=False, fail_delete=False):
        self.tables, self.loads, self.deleted = {}, [], []
        self.drop, self.fail, self.fail_delete = drop, fail, fail_delete
        self.gate = None

    def load_typed_csv(self, table, path, columns):
        if self.gate:
            self.gate.wait(10)
        assert table not in self.tables  # WRITE_EMPTY
        raw = Path(path).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
        assert next(reader) == [name for name, _ in columns]
        rows = []
        for record in reader:
            assert len(record) == len(columns)
            rows.append([None if value == "" else PARSE[data.SYNTHETIC_TYPES[kind]](value)
                         for value, (_, kind) in zip(record, columns)])
        self.loads.append((table, list(columns)))
        if self.fail:
            raise RuntimeError("provider error with https://secret.example/token")
        self.tables[table] = (list(columns), rows[:len(rows) - self.drop])
        return len(self.tables[table][1])

    def profile(self, table):
        columns, rows = self.tables[table]
        result = []
        for i, (name, kind) in enumerate(columns):
            values = [row[i] for row in rows if row[i] is not None]
            bq = data.SYNTHETIC_TYPES[kind]
            result.append({"name": name, "type": "number" if kind in ("integer", "number") else kind,
                           "sample": [str(v) for v in values[:3]], "bq_type": bq, "date_like": False,
                           "null_pct": 100 * (len(rows) - len(values)) / len(rows) if rows else 0,
                           "distinct_count": len(set(values)), "min": None, "max": None})
        return {"row_count": len(rows), "columns": result}

    def delete_loaded_table(self, table):
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.deleted.append(table)
        self.tables.pop(table, None)
        return True


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fake = FakeTypedBigQuery()
    app = create_app(Config(data_dir=tmp_path, gcp_project_id="test-project"),
                     model_lister=fake_models, bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        def no_model(_):
            raise AssertionError("synthetic generation must not call a model")
        monkeypatch.setattr(app.state.models, "llm_for", no_model)
        yield client, app, fake


def create(client):
    response = client.post("/api/builds", json={"archetype": "executive", "mode": "data"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def wait(app):
    for _ in range(1000):
        if not app.state.engine_tasks:
            return
        time.sleep(.01)
    raise AssertionError("generation did not finish")


def post(client, bid, key="sample_001", spec=SPEC, proposal_id=None):
    return client.post(f"/api/builds/{bid}/synthetic-data",
                       json={"generation_key": key, "proposal_id": proposal_id, "spec": spec})


def generate(client, app, bid, key="sample_001", spec=SPEC):
    response = post(client, bid, key, spec)
    assert response.status_code == 202, response.text
    wait(app)
    return response.json()["run_id"], client.get(f"/api/builds/{bid}/synthetic-data/jobs/{key}").json()


def column(name, kind, generator, nullable=0):
    return {"name": name, "type": kind, "nullable_fraction": nullable, "generator": generator}


def events(app, run_id):
    with app.state.db.connect() as conn:
        return [(r["kind"], json.loads(r["payload_json"])) for r in
                conn.execute("SELECT kind,payload_json FROM events WHERE run_id=? ORDER BY rowid", (run_id,))]


def test_generate_registers_synthetic_source(setup):
    client, app, fake = setup
    bid = create(client)
    run_id, status = generate(client, app, bid)
    assert status == {"generation_key": "sample_001", "run_id": run_id, "state": "succeeded",
                      "source_id": status["source_id"], "retry_ready": False, "error": None}
    build = client.get(f"/api/builds/{bid}").json()
    [source] = build["sources"]
    assert source["id"] == status["source_id"] and source["kind"] == "synthetic"
    assert source["name"] == "Synthetic sample data" and source["row_count"] == 1000
    assert source["bq_table"] == f"test-project.dss_demo.src_{bid}_synthetic_{source['id'][2:]}"
    assert fake.loads == [(source["bq_table"], [("region", "string"), ("quantity", "integer"),
                                                ("unit_price", "number"), ("revenue", "number")])]
    # Local storage: the server-derived prefix, metadata.json written as the completion record.
    folder = app.state.settings.get().data_dir / "generated" / bid / "sample_001"
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    content = (folder / "sample.csv").read_bytes()
    assert meta["row_count"] == 1000 and meta["bytes"] == len(content) and meta["synthetic"] is True
    assert meta["sha256"] == node.digest(folder / "sample.csv")[1] and meta["source_id"] == source["id"]
    # Provenance doc with seed, row count, checksum, schema, version and assumptions.
    doc = (app.state.settings.get().data_dir / "builds" / bid / "v1/docs/synthetic-data.md").read_text(encoding="utf-8")
    front = yaml.safe_load(doc.split("---", 2)[1])
    assert front["type"] == "Synthetic Dataset" and front["seed"] == 42 and front["row_count"] == 1000
    assert front["sha256"] == meta["sha256"] and front["generator_version"] == synthetic.GENERATOR_VERSION
    assert [c["name"] for c in front["schema"]] == ["region", "quantity", "unit_price", "revenue"]
    assert front["assumptions"] and "invented" in doc
    assert {"path": "synthetic-data.md", "title": "Synthetic sample data", "type": "Synthetic Dataset"} in build["docs"]
    index = (app.state.settings.get().data_dir / "builds" / bid / "v1/docs/index.md").read_text(encoding="utf-8")
    assert "(synthetic-data.md)" in index and "(data-profile.md)" in index
    # Datasets endpoint and download.
    [dataset] = client.get(f"/api/builds/{bid}/synthetic-data").json()
    assert dataset == {"source_id": source["id"], "generation_key": "sample_001", "synthetic": True,
                       "spec": SPEC, "assumptions": front["assumptions"],
                       "generator_version": synthetic.GENERATOR_VERSION, "sha256": meta["sha256"],
                       "bytes": len(content), "created_at": dataset["created_at"]}
    download = client.get(f"/api/builds/{bid}/synthetic-data/{source['id']}/csv")
    assert download.status_code == 200 and download.content == content
    assert download.headers["content-type"].startswith("text/csv")
    assert 'filename="synthetic-sample.csv"' in download.headers["content-disposition"]
    # One run, one trace, existing event shapes only.
    kinds = [kind for kind, _ in events(app, run_id)]
    assert kinds[0] == "run.started" and kinds[-1] == "run.finished"
    assert {"build.updated", "docs.updated"} <= set(kinds)
    assert events(app, run_id)[-1][1] == {"run_id": run_id, "node": "synthetic_generate", "status": "ok", "error": None}
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT node,status FROM traces WHERE run_id=?", (run_id,)).fetchall()
    assert [tuple(t) for t in traces] == [("synthetic_generate", "ok")]
    assert build["stage"] == "connect"


def test_replay_conflict_and_in_flight(setup):
    client, app, fake = setup
    bid = create(client)
    fake.gate = threading.Event()
    first = post(client, bid)
    assert first.status_code == 202
    # In flight: replay returns the original run; another key is refused by the action lock.
    assert post(client, bid).json() == first.json()
    busy = post(client, bid, key="other")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "wrong_stage"
    queued = client.get(f"/api/builds/{bid}/synthetic-data/jobs/sample_001").json()
    assert queued["state"] in ("queued", "generating", "loading") and queued["retry_ready"] is False
    assert queued["source_id"] is None and queued["error"] is None
    fake.gate.set()
    wait(app)
    # Replay after success (sources now exist) still returns the original run and adds nothing.
    again = post(client, bid)
    assert again.status_code == 202 and again.json() == first.json()
    wait(app)
    assert len(client.get(f"/api/builds/{bid}").json()["sources"]) == 1 and len(fake.loads) == 1
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM traces WHERE node='synthetic_generate'").fetchone()[0] == 1
    # A key-order change is the same canonical request; any value change conflicts.
    reordered = {key: SPEC[key] for key in reversed(list(SPEC))}
    assert post(client, bid, spec=reordered).json() == first.json()
    changed = post(client, bid, spec={**SPEC, "seed": 7})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "synthetic_request_conflict"
    # A new key on a build with a source never replaces or mixes with it.
    refused = post(client, bid, key="sample_002")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "synthetic_requires_empty_build"


def test_rejections(setup):
    client, app, fake = setup
    bid = create(client)
    stale = client.post(f"/api/builds/{bid}/synthetic-data", json=REQUEST)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "synthetic_proposal_stale"
    bad = post(client, bid, spec={**SPEC, "row_count": 0})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_generation_spec"
    assert bad.json()["error"]["detail"]["field"] == "row_count"
    formula = post(client, bid, spec={**SPEC, "columns": [column("name", "string", {"kind": "choice", "values": ["=1+1"]})]})
    assert formula.status_code == 422 and formula.json()["error"]["detail"]["field"].startswith("columns[0]")
    for body in ({"generation_key": "bad key!", "proposal_id": None, "spec": SPEC},
                 {"generation_key": "k" * 65, "proposal_id": None, "spec": SPEC},
                 {"generation_key": "ok", "spec": SPEC},
                 {"generation_key": "ok", "proposal_id": None, "spec": SPEC, "extra": 1}):
        response = client.post(f"/api/builds/{bid}/synthetic-data", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request", body
    duplicate = client.post(f"/api/builds/{bid}/synthetic-data", headers={"content-type": "application/json"},
                            content=b'{"generation_key":"a","generation_key":"b","proposal_id":null,"spec":{}}')
    assert duplicate.status_code == 422 and duplicate.json()["error"]["code"] == "invalid_request"
    large = client.post(f"/api/builds/{bid}/synthetic-data", headers={"content-type": "application/json"},
                        content=b" " * (synthetic.MAX_REQUEST_BYTES + 1))
    assert large.status_code == 413 and large.json()["error"].keys() == {"code", "message", "detail"}
    assert post(client, "b_missing").json()["error"]["code"] == "build_not_found"
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (bid,))
    wrong = post(client, bid)
    assert wrong.status_code == 409 and wrong.json()["error"] == {
        "code": "wrong_stage", "message": wrong.json()["error"]["message"], "detail": {"stage": "prototype"}}
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='interview' WHERE id=?", (bid,))
        conn.execute("INSERT INTO sources VALUES('s_real',?,'upload','sales.csv','p.d.t',3,'[]')", (bid,))
    real = post(client, bid)
    assert real.status_code == 409 and real.json()["error"]["code"] == "synthetic_requires_empty_build"
    app.state.settings.update({"gcp_project_id": ""})
    other = create(client)
    assert post(client, other).json()["error"]["code"] == "gcp_not_configured"
    assert not fake.loads
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM synthetic_generations").fetchone()[0] == 0


def test_typed_load_keeps_ids_nulls_and_empty_rows(setup):
    client, app, fake = setup
    bid = create(client)
    spec = {"schema_version": 1, "row_count": 500, "seed": 3, "columns": [
        column("code", "string", {"kind": "choice", "values": ["001", "010"]}, nullable=.5),
        column("empty_metric", "integer", {"kind": "integer", "min": 1, "max": 9}, nullable=1),
        column("empty_amount", "number", {"kind": "decimal", "min": 0, "max": 5, "decimals": 2}, nullable=1),
        column("empty_day", "date", {"kind": "date", "start": "2026-01-01", "end": "2026-12-31"}, nullable=1),
        column("empty_flag", "boolean", {"kind": "boolean", "true_probability": .5}, nullable=1)]}
    _, status = generate(client, app, bid, spec=spec)
    assert status["state"] == "succeeded", status
    [source] = client.get(f"/api/builds/{bid}").json()["sources"]
    columns, rows = fake.tables[source["bq_table"]]
    assert columns == [("code", "string"), ("empty_metric", "integer"), ("empty_amount", "number"),
                       ("empty_day", "date"), ("empty_flag", "boolean")]
    assert len(rows) == source["row_count"] == 500
    assert {row[0] for row in rows} == {"001", "010", None}
    assert all(row[1:] == [None] * 4 for row in rows)
    empty = sum(row == [None] * 5 for row in rows)
    assert 0 < empty < 500  # all-empty records survive (prepare_csv would drop them)
    csv_text = (app.state.settings.get().data_dir / "generated" / bid / "sample_001" / "sample.csv").read_text()
    assert "\n,,,,\n" in csv_text
    # One column, every value null: csv.writer writes `""` lines; still the exact row count.
    other = create(client)
    nulls = {"schema_version": 1, "row_count": 25, "seed": 1,
             "columns": [column("only", "integer", {"kind": "integer", "min": 0, "max": 1}, nullable=1)]}
    _, status = generate(client, app, other, spec=nulls)
    [source] = client.get(f"/api/builds/{other}").json()["sources"]
    assert status["state"] == "succeeded" and source["row_count"] == 25
    assert fake.tables[source["bq_table"]][1] == [[None]] * 25


def test_real_loader_declares_schema_and_null_marker(tmp_path):
    client = Mock()
    client.get_table.return_value.num_rows = 2
    sent = {}
    client.load_table_from_file.side_effect = lambda handle, table, **kw: sent.update(body=handle.read(), table=table, **kw) or Mock()
    service = data.BigQuery(Config(data_dir=tmp_path, gcp_project_id="p", bq_dataset="d"), client=client)
    path = tmp_path / "sample.csv"
    path.write_bytes(b'id,amount\n001,\n,\n')
    columns = [(n, k) for n, k in zip(("id", "amount", "day", "flag", "count"), ("string", "number", "date", "boolean", "integer"))]
    assert service.load_typed_csv("p.d.t", path, columns) == 2
    config = sent["job_config"]
    assert sent["body"] == path.read_bytes() and sent["table"] == "p.d.t"
    assert sent["job_id"] == data.BigQuery.load_job_id("p.d.t")
    assert config.autodetect is False and config.null_marker == "" and config.skip_leading_rows == 1
    assert config.write_disposition == "WRITE_EMPTY" and config.max_bad_records == 0
    assert [(f.name, f.field_type, f.mode) for f in config.schema] == [
        ("id", "STRING", "NULLABLE"), ("amount", "NUMERIC", "NULLABLE"), ("day", "DATE", "NULLABLE"),
        ("flag", "BOOLEAN", "NULLABLE"), ("count", "INTEGER", "NULLABLE")]
    assert config.source_column_match is None and config.to_api_repr()["load"]["nullMarker"] == ""


@pytest.mark.parametrize("fake_args, code", [({"drop": 1}, "synthetic_load_failed"),
                                             ({"fail": True}, "synthetic_load_failed")])
def test_load_failure_cleans_and_allows_retry(tmp_path, monkeypatch, fake_args, code):
    fake = FakeTypedBigQuery(**fake_args)
    app = create_app(Config(data_dir=tmp_path, gcp_project_id="test-project"),
                     model_lister=fake_models, bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        bid = create(client)
        run_id, status = generate(client, app, bid)
        assert status["state"] == "failed" and status["retry_ready"] is True and status["source_id"] is None
        assert status["error"]["code"] == code and "Retry is available" in status["error"]["message"]
        assert "secret" not in json.dumps(status) and "secret" not in json.dumps(events(app, run_id))
        assert events(app, run_id)[-1][1]["status"] == "error" and events(app, run_id)[-1][1]["error"] == code
        build = client.get(f"/api/builds/{bid}").json()
        assert build["sources"] == [] and build["docs"] == [] and build["stage"] == "connect"
        assert fake.deleted == [fake.loads[0][0]] and not fake.tables
        assert not (tmp_path / "generated" / bid / "sample_001").exists()
        assert client.get(f"/api/builds/{bid}/synthetic-data").json() == []
        # Explicit retry with a new key after cleanup succeeds; the failed job stays failed.
        fake.drop, fake.fail = 0, False
        _, retry = generate(client, app, bid, key="sample_002")
        assert retry["state"] == "succeeded"
        assert client.get(f"/api/builds/{bid}/synthetic-data/jobs/sample_001").json()["state"] == "failed"
        assert len(client.get(f"/api/builds/{bid}").json()["sources"]) == 1


def test_generation_and_cleanup_failures(setup, monkeypatch):
    client, app, fake = setup
    bid = create(client)

    def too_big(spec, output_path):
        raise synthetic.SyntheticError("output", f"{output_path} exceeds the 50 MiB budget")
    with monkeypatch.context() as patch:
        patch.setattr(node, "generate_csv", too_big)
        _, status = generate(client, app, bid)
    assert status["state"] == "failed" and status["error"]["code"] == "synthetic_generation_failed"
    assert status["retry_ready"] is True and not fake.loads and str(app.state.settings.get().data_dir) not in json.dumps(status)
    fake.drop, fake.fail_delete = 1, True
    _, status = generate(client, app, bid, key="sample_002")
    assert status["state"] == "failed" and status["retry_ready"] is False
    assert "after cleanup" in status["error"]["message"]
    # No BigQuery client (e.g. missing credentials): no load can exist, so the job is retryable.
    def no_client(_):
        raise RuntimeError("could not find default credentials")
    app.state.bigquery_factory = no_client
    _, status = generate(client, app, bid, key="sample_003")
    assert status["state"] == "failed" and status["error"]["code"] == "synthetic_load_failed"
    assert status["retry_ready"] is True and not (app.state.settings.get().data_dir / "generated" / bid / "sample_003").exists()


def test_storage_paths_metadata_last(tmp_path, monkeypatch):
    spec = synthetic.parse_spec(SPEC)
    order, outputs = [], []
    real_generate, real_copy, real_write = node.generate_csv, node.copy_file, node.write_json
    monkeypatch.setattr(node, "generate_csv", lambda s, out: outputs.append(Path(out)) or real_generate(s, out))
    monkeypatch.setattr(node, "copy_file", lambda a, b: order.append(Path(b).name) or real_copy(a, b))
    monkeypatch.setattr(node, "write_json", lambda p, d: order.append(Path(p).name) or real_write(p, d))
    local = Config(data_dir=tmp_path / "local")
    result = node.store(local, "b_1", "k1", spec, {"generation_key": "k1"})
    folder = tmp_path / "local/generated/b_1/k1"
    assert outputs == [folder / "sample.csv"] and order == ["metadata.json"]
    assert sorted(p.name for p in folder.iterdir()) == ["metadata.json", "sample.csv"]
    assert json.loads((folder / "metadata.json").read_text())["sha256"] == result.sha256
    # Hosted: generate on local temp disk, copy to the volume, verify, then metadata last.
    hosted = Config(data_dir=tmp_path / "volume", cloud_service="dss")
    order.clear()
    again = node.store(hosted, "b_1", "k1", spec, {"generation_key": "k1"})
    assert not outputs[1].is_relative_to(tmp_path / "volume") and not outputs[1].exists()
    assert order == ["sample.csv", "metadata.json"] and again.sha256 == result.sha256
    volume = tmp_path / "volume/generated/b_1/k1"
    assert node.digest(volume / "sample.csv") == (result.bytes, result.sha256)
    # A copy that does not match its checksum never gets a completion record.
    monkeypatch.setattr(node, "copy_file", lambda a, b: Path(b).write_bytes(b"torn"))
    with pytest.raises(node.Failure):
        node.store(hosted, "b_1", "k2", spec, {})
    assert not (tmp_path / "volume/generated/b_1/k2/metadata.json").exists()


def test_jobs_read_persisted_state(setup):
    client, app, fake = setup
    bid = create(client)
    with app.state.db.connect() as conn:
        for i in range(22):
            conn.execute("INSERT INTO synthetic_generations(generation_key,build_id,request_hash,run_id,source_id,"
                         "bq_table,state,retry_ready,error_json,created_at,spec_json,assumptions_json) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,'{}','[]')",
                         (f"k{i:02d}", bid, "h", f"r_{i:012d}", f"s_{i:012d}", "p.d.t", "queued" if i == 21 else "failed",
                          1, json.dumps({"code": "synthetic_load_failed", "message": "m"}), f"2026-10-20T00:00:{i:02d}Z"))
    jobs = client.get(f"/api/builds/{bid}/synthetic-data/jobs").json()
    assert [j["generation_key"] for j in jobs] == [f"k{i:02d}" for i in range(21, 1, -1)]
    assert jobs[0] == {"generation_key": "k21", "run_id": "r_000000000021", "state": "queued", "source_id": None,
                       "retry_ready": False, "error": None}
    assert jobs[1]["retry_ready"] is True and jobs[1]["error"]["code"] == "synthetic_load_failed"
    missing = client.get(f"/api/builds/{bid}/synthetic-data/jobs/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    # Reading status never launches or resumes work.
    assert not app.state.engine_tasks and not fake.loads and bid not in app.state.harness.active_builds
    assert client.get(f"/api/builds/{bid}/synthetic-data/jobs/k21").json()["state"] == "queued"
    assert client.get("/api/builds/b_missing/synthetic-data/jobs").json()["error"]["code"] == "build_not_found"


def test_download_scope(setup):
    client, app, fake = setup
    bid, other = create(client), create(client)
    _, status = generate(client, app, bid)
    source_id = status["source_id"]
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO sources VALUES('s_real',?,'upload','sales.csv','p.d.t',3,'[]')", (other,))
    assert client.get(f"/api/builds/{bid}/synthetic-data/{source_id}/csv").status_code == 200
    for build, source in ((other, source_id), (other, "s_real"), (bid, "s_real"), (bid, "s_unknown"),
                          (bid, "..%2f..%2fdss.sqlite"), ("b_missing", source_id)):
        response = client.get(f"/api/builds/{build}/synthetic-data/{source}/csv")
        assert response.status_code == 404 and response.json()["error"]["code"] in ("not_found", "build_not_found")
    # A file changed after registration is never served.
    path = app.state.settings.get().data_dir / "generated" / bid / "sample_001" / "sample.csv"
    path.write_bytes(path.read_bytes().replace(b"East", b"Easy", 1))
    assert client.get(f"/api/builds/{bid}/synthetic-data/{source_id}/csv").status_code == 404
