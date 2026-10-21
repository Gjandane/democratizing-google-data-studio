import csv
from collections import Counter
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from fastapi.testclient import TestClient
from google.cloud import bigquery

from dss.config import Config
from dss.data import bigquery as data
from dss.main import create_app
from fakes import fake_models

SALES = (Path(__file__).parent / "data/small_sales.csv").read_bytes()


class FakeBigQuery:
    """In-memory load/profile service; never obtains credentials or calls a network."""
    def __init__(self):
        self.tables = {}
        self.loads = []
        self.gcs = {"gs://example-bucket/sales.csv": SALES}

    def download_gcs(self, uri):
        return self.gcs[uri]

    def load_csv(self, table, content, *, uri=None):
        normalized, schema, _ = data.prepare_csv(content)
        rows = list(csv.DictReader(io.StringIO(normalized.decode())))
        self.tables[table] = (schema, rows)
        self.loads.append((table, uri, normalized))

    def profile(self, table):
        schema, rows = self.tables[table]
        cols = []
        for field in schema:
            values = [row[field.name] for row in rows if row[field.name] != ""]
            kind = "number" if field.field_type in ("FLOAT", "INTEGER") else "date" if field.field_type == "DATE" else "string"
            cols.append({"name": field.name, "type": kind, "sample": values[:3], "bq_type": field.field_type,
                         "values": [{"value": value[:60], "count": count} for value, count in Counter(values).most_common(20 if len(set(values)) <= 20 else 5)],
                         "values_complete": len(set(values)) <= 20,
                         "date_like": field.field_type == "STRING" and bool(values) and all(data.is_date(v) for v in values[:3]),
                         "null_pct": 100 * (len(rows) - len(values)) / len(rows) if rows else 0,
                         "distinct_count": len(set(values)), "min": min(values) if values else None,
                         "max": max(values) if values else None})
        return {"row_count": len(rows), "columns": cols}


@pytest.fixture
def setup(tmp_path):
    fake = FakeBigQuery()
    app = create_app(Config(data_dir=tmp_path, gcp_project_id="test-project"),
                     model_lister=fake_models, bigquery_factory=lambda _: fake)
    with TestClient(app) as client:
        yield client, app, fake


def create(client, **kwargs):
    response = client.post("/api/builds", json={"archetype": "executive", "mode": "data", **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, build_id, files=None):
    return client.post(f"/api/builds/{build_id}/sources/upload", files=files or [("files", ("sales.csv", SALES, "text/csv"))])


def profile_doc(app, build):
    text = (app.state.settings.get().data_dir / "builds" / build["id"] / "v1/docs/data-profile.md").read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


def assert_shape(value, fixture):
    if isinstance(fixture, dict):
        assert value.keys() == fixture.keys()
        for key in fixture:
            if key in ("spec_version", "report_url", "notes"):
                assert value[key] is None or isinstance(value[key], int if key == "spec_version" else str)
            else:
                assert_shape(value[key], fixture[key])
    elif isinstance(fixture, list):
        assert isinstance(value, list)
        for item in value:
            assert_shape(item, fixture[0])
    else:
        assert type(value) is type(fixture)


def test_create_list_get_and_shapes(setup):
    client, app, fake = setup
    first = create(client)
    assert first["stage"] == "connect" and first["current_version"] == 1
    assert first["notes"] is None and first["spec_version"] is None
    assert set(first["artifacts"].values()) == {"missing"} and "ready_for_plan" not in first
    assert first["sources"] == first["docs"] == []
    assert first["versions"][0]["status"] == "draft"
    second = create(client, title="Second")
    assert client.get("/api/builds").json()[0]["id"] == second["id"]
    assert client.get(f'/api/builds/{first["id"]}').json() == first
    upload(client, first["id"])
    updated = client.get(f'/api/builds/{first["id"]}').json()
    fixtures = Path(__file__).parents[2] / "contracts/fixtures/api"
    assert_shape(updated, json.loads((fixtures / "build.json").read_text()))
    assert_shape(client.get("/api/builds").json(), json.loads((fixtures / "builds.json").read_text()))
    assert client.get("/api/builds").json()[0]["id"] == first["id"]
    assert client.get("/api/builds/missing").json()["error"]["code"] == "build_not_found"
    assert client.post("/api/builds", json={"archetype": "bad", "mode": "data"}).status_code == 422


def test_multi_upload_profile_and_trace(setup):
    client, app, fake = setup
    build = create(client)
    response = upload(client, build["id"], [("files", ("sales.csv", SALES)), ("files", ("other.csv", SALES))])
    assert response.status_code == 201, response.text
    sources = response.json()["sources"]
    assert len(sources) == 2 and sources[0]["bq_table"] != sources[1]["bq_table"]
    for source in sources:
        assert source["row_count"] == 3
        assert source["columns"][0] == {"name": "order_date", "type": "date", "sample": ["2026-01-03", "2026-01-04", "2026-01-05"]}
        assert source["columns"][2]["type"] == "number"
        assert all(len(col["sample"]) == 3 for col in source["columns"])
    profile = profile_doc(app, build)
    assert profile["type"] == "BigQuery Table" and len(profile["sources"]) == 2
    assert profile['sources'][0]['columns'][0]['values_complete']
    from dss.data.profile import prompt_text
    body = (app.state.settings.get().data_dir / 'builds' / build['id'] / 'v1/docs/data-profile.md').read_text(encoding='utf-8')
    assert prompt_text(profile['sources'][0]) in body
    docs = app.state.settings.get().data_dir / "builds" / build["id"] / "v1/docs"
    for path in docs.glob("*.md"):
        assert yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])["type"]
    with app.state.db.connect() as db:
        traces = db.execute("SELECT * FROM traces ORDER BY rowid").fetchall()
        assert len(traces) == 2 and all(row["status"] == "ok" for row in traces)
        assert [span["node"] for span in json.loads(traces[-1]["spans_json"])] == ["router", "intake", "guardrail"]
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        events = [(r[0], json.loads(r[1])) for r in db.execute("SELECT kind,payload_json FROM events ORDER BY rowid")]
        assert events[-1][0] == "build.updated"
        assert events[-1][1]["build"]["sources"] == sources


def test_latin1_duplicate_headers_and_reupload(setup):
    client, app, fake = setup
    build = create(client)
    content = "Name,Order Date,Order Date,order_date_2\nCafé,01/03/2026,01/04/2026,01/05/2026\n".encode("latin-1")
    response = upload(client, build["id"], [("files", ("../x.csv", content))])
    assert response.status_code == 201
    first = response.json()["sources"][0]
    assert first["name"] == "x.csv"
    assert [c["name"] for c in first["columns"]] == ["name", "order_date", "order_date_2", "order_date_2_2"]
    assert first["columns"][0]["sample"] == ["Café"]
    assert profile_doc(app, build)["sources"][0]["columns"][1]["date_like"] is True
    again = upload(client, build["id"], [("files", ("x.csv", SALES))]).json()["sources"][0]
    assert first["bq_table"] != again["bq_table"]
    assert len(profile_doc(app, build)["sources"]) == 2


@pytest.mark.parametrize("content", [b"", b"a,b\n", b"a,b\n\n", b"a,b\n1\n", b'a,b\n"bad,2', b"a\n\x00"])
def test_invalid_csv(setup, content):
    client, app, fake = setup
    build = create(client)
    response = upload(client, build["id"], [("files", ("empty.csv", content))])
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_source"
    assert response.json()["error"]["detail"]["reason"]
    assert fake.loads == []


def test_size_limit_and_batch_validation(setup):
    client, app, fake = setup
    build = create(client)
    # Real 100 MiB + 1 payload, exercising the configured production limit.
    response = upload(client, build["id"], [("files", ("large.csv", b"x" * (data.MAX_SOURCE_BYTES + 1)))])
    assert response.status_code == 422 and "100 MB" in response.json()["error"]["detail"]["reason"]
    response = upload(client, build["id"], [("files", ("valid.csv", SALES)), ("files", ("empty.csv", b""))])
    assert response.status_code == 422 and fake.loads == []
    assert upload(client, build["id"], [("files", ("bad.txt", SALES))]).status_code == 422


def test_gcs_and_existing_bigquery(setup):
    client, app, fake = setup
    build = create(client)
    url = f'/api/builds/{build["id"]}/sources'
    response = client.post(url, json={"kind": "gcs", "uri": "gs://example-bucket/sales.csv"})
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["kind"] == "gcs" and source["row_count"] == 3
    assert fake.loads[0][1] == "gs://example-bucket/sales.csv"
    table = "other-project.dataset.existing"
    fake.tables[table] = fake.tables[source["bq_table"]]
    response = client.post(url, json={"kind": "bigquery", "uri": table})
    assert response.status_code == 201 and response.json()["bq_table"] == table
    assert len(fake.loads) == 1
    for kind, uri in [("gcs", "https://example.com/data.csv"), ("gcs", "gs://b/*.csv"), ("gcs", "gs://[bucket/sales.csv"), ("bigquery", "p.d.t` WHERE TRUE")]:
        response = client.post(url, json={"kind": kind, "uri": uri})
        assert response.status_code == 422 and response.json()["error"]["detail"]["reason"]


def test_missing_project_and_source_failure(setup, caplog):
    client, app, fake = setup
    build = create(client)
    app.state.settings.update({"gcp_project_id": ""})
    response = upload(client, build["id"])
    assert response.status_code == 503 and response.json()["error"]["code"] == "gcp_not_configured"
    assert fake.loads == []
    app.state.settings.update({"gcp_project_id": "test-project"})
    fake.load_csv = Mock(side_effect=RuntimeError("secret-provider-content"))
    response = upload(client, build["id"])
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"]
    assert "secret-provider-content" not in response.text + caplog.text
    assert client.get(f'/api/builds/{build["id"]}').json()["sources"] == []
    assert not app.state.harness.active_builds
    with app.state.db.connect() as db:
        trace = db.execute("SELECT * FROM traces ORDER BY rowid DESC LIMIT 1").fetchone()
        assert trace["status"] == "error" and trace["error"] == "invalid_source"


def test_adapter_jobs_and_profile():
    config = Config(gcp_project_id="test-project")
    client = Mock()
    client.get_table.return_value = SimpleNamespace(schema=[bigquery.SchemaField("event_date", "STRING")])
    client.query.return_value.result.return_value = [{"row_count": 4, "c0": {"null_count": 1, "distinct_count": 2,
        "min_value": "2026-01-03", "max_value": "2026-01-04", "invalid_dates": 0,
        "value_counts": [{'value': '01/03/2026', 'count': 2}, {'value': '01/04/2026', 'count': 1}]}}]
    service = data.BigQuery(config, client=client)
    service.load_csv("test-project.dss_demo.sales", SALES)
    call = client.load_table_from_file.call_args
    assert b"order_date" in call.args[0].getvalue()
    job_config = call.kwargs["job_config"]
    assert job_config.autodetect and job_config.skip_leading_rows == 1
    assert job_config.source_column_match is None and job_config.encoding == "UTF-8"
    assert job_config.write_disposition == "WRITE_EMPTY"
    service.gcs_generations["gs://bucket/test.csv"] = "123"
    service.current_generation = Mock(return_value="123")
    service.load_csv("test-project.dss_demo.gcs", "Name\nCafé\n".encode("latin-1"), uri="gs://bucket/test.csv")
    assert client.load_table_from_uri.call_args.kwargs["job_config"].encoding == "ISO-8859-1"
    uri_config = client.load_table_from_uri.call_args.kwargs["job_config"]
    assert uri_config.source_column_match == "POSITION" and uri_config.autodetect is False
    profile = service.profile("test-project.dss_demo.existing")
    col = profile["columns"][0]
    assert profile["row_count"] == 4 and col["date_like"] is True and col["null_pct"] == 25
    assert col["distinct_count"] == 2 and col['values_complete'] and len(col["sample"]) == 2
    sql = client.query.call_args.args[0]
    assert "COUNTIF(`event_date` IS NULL)" in sql and 'APPROX_TOP_COUNT' in sql
    assert "`test-project.dss_demo.existing`" in sql
    service.current_generation.side_effect = ["123", "456"]
    with pytest.raises(Exception, match="Source could not be loaded") as error:
        service.load_csv("test-project.dss_demo.changed", SALES, uri="gs://bucket/test.csv")
    assert "changed" in error.value.detail["reason"]


@pytest.mark.parametrize("field_type,expected", [("INTEGER", "number"), ("NUMERIC", "number"), ("DATE", "date"), ("TIMESTAMP", "datetime"), ("BOOLEAN", "boolean"), ("GEOGRAPHY", "geo")])
def test_profile_type_mapping(field_type, expected):
    client = Mock()
    client.get_table.return_value = SimpleNamespace(schema=[bigquery.SchemaField("order", field_type)])
    client.query.return_value.result.return_value = [{"row_count": 3, "c0": {"null_count": 0, "distinct_count": 3,
        "min_value": None, "max_value": None, "invalid_dates": 0,
        "value_counts": [{'value': v, 'count': 1} for v in ('a', 'b', 'c')]}}]
    service = data.BigQuery(Config(gcp_project_id="test-project"), client=client)
    assert service.profile("test-project.dss_demo.existing")["columns"][0]["type"] == expected


def test_gcs_download_bounded():
    session = Mock()
    metadata, media = Mock(), Mock()
    metadata.json.return_value = {"size": str(len(SALES)), "generation": "123"}
    media.iter_content.return_value = [SALES]
    metadata.__enter__ = Mock(return_value=metadata)
    metadata.__exit__ = Mock(return_value=False)
    media.__enter__ = Mock(return_value=media)
    media.__exit__ = Mock(return_value=False)
    session.get.side_effect = [metadata, media]
    service = data.BigQuery(Config(gcp_project_id="test-project"), client=Mock(), storage_session=session)
    assert service.download_gcs("gs://example-bucket/folder/sales.csv") == SALES
    assert "folder%2Fsales.csv" in session.get.call_args.args[0]
    assert session.get.call_args.kwargs["params"]["generation"] == "123"
    session.get.side_effect = None
    session.get.return_value = metadata
    metadata.json.return_value = {"size": str(data.MAX_SOURCE_BYTES + 1)}
    with pytest.raises(Exception, match="Source could not be loaded"):
        service.download_gcs("gs://example-bucket/sales.csv")


def test_partial_batch_can_retry(setup):
    client, app, fake = setup
    build = create(client)
    real_load = fake.load_csv
    calls = []
    def fail_second(table, content, *, uri=None):
        calls.append(table)
        if len(calls) == 2:
            raise RuntimeError("Temporary data service failure")
        assert table not in fake.tables, "WRITE_EMPTY refuses an existing table"
        real_load(table, content, uri=uri)
    fake.load_csv = fail_second
    files = [("files", ("sales.csv", SALES)), ("files", ("other.csv", SALES))]
    assert upload(client, build["id"], files).status_code == 422
    assert client.get(f'/api/builds/{build["id"]}').json()["sources"] == []
    response = upload(client, build["id"], files)
    assert response.status_code == 201
    assert len(response.json()["sources"]) == 2
    assert calls[0] not in {source["bq_table"] for source in response.json()["sources"]}


def test_long_fields_and_nonfinite_numeric_strings():
    content = ('Description,Value\n' + 'x' * 140000 + ',1e999\n').encode()
    normalized, schema, encoding = data.prepare_csv(content)
    assert [field.field_type for field in schema] == ["STRING", "STRING"]
    assert len(list(csv.reader(io.StringIO(normalized.decode())))[1][0]) == 140000


def test_nested_profile_and_empty_table():
    client = Mock()
    client.get_table.return_value = SimpleNamespace(schema=[bigquery.SchemaField("items", "INTEGER", mode="REPEATED")])
    client.query.return_value.result.return_value = [{"row_count": 3, "c0": {"null_count": 0, "distinct_count": 2,
        "min_value": None, "max_value": None, "invalid_dates": 0,
        "value_counts": [{'value': '[1]', 'count': 2}, {'value': '[3]', 'count': 1}]}}]
    service = data.BigQuery(Config(gcp_project_id="test-project"), client=client)
    assert service.profile("test-project.dss_demo.existing")["columns"][0]["type"] == "string"
    assert "TO_JSON_STRING(`items`)" in client.query.call_args.args[0]
    client.query.return_value.result.return_value = [{"row_count": 0, "null_count": 0, "distinct_count": 0,
        "min_value": None, "max_value": None, "samples": None}]
    with pytest.raises(Exception, match="Source could not be loaded"):
        service.profile("test-project.dss_demo.existing")
